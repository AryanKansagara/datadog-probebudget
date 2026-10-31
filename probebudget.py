"""Budgeted local HTTP instrumentation experiment. No Datadog adapter or inference."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
import math
from pathlib import Path
import random
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener

SECRET='PROBEBUDGET_FORBIDDEN_TOKEN_7fd91'
CORE=('cache','attempts','downstream')
PROBES=CORE+('heartbeat','context')
# A literal field allowlist, applied before any serialization. No locals()/object dump.
ALLOW={'cache':('stale',),'attempts':('count',),'downstream':('band',),
       'heartbeat':('alive',),'context':('routes',)}
FAULTS={'healthy':(), 'stale':('stale',), 'slow':('slow',), 'retry':('retry',),
        'dual':('stale','retry'), 'unmodeled':('cpu',)}

def encode(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def allowed_frame(probe, context):
    if probe not in ALLOW:
        raise ValueError('unknown probe')
    values={key:context[key] for key in ALLOW[probe]}
    # Schema of authored allowlisted values: callers cannot insert arbitrary nested objects.
    if probe=='cache' and type(values['stale']) is not bool:raise ValueError('bad stale')
    if probe=='attempts' and type(values['count']) is not int:raise ValueError('bad count')
    if probe=='downstream' and values['band'] not in ('slow','normal'):raise ValueError('bad band')
    if probe=='heartbeat' and values['alive'] is not True:raise ValueError('bad heartbeat')
    if probe=='context' and values['routes'] != ['/checkout','/inventory']*20:raise ValueError('bad routes')
    return {'probe':probe,'values':values}

class Service:
    def __init__(self, fault):
        if fault not in FAULTS:raise ValueError('unknown fixture fault')
        self.faults=FAULTS[fault]
        self.cache_written=time.monotonic()-(120 if 'stale' in self.faults else 0)
        self.requests=0

    def execute(self, probes, budget):
        if (type(probes) is not list or len(probes)>len(PROBES)
            or any(type(p) is not str or p not in PROBES for p in probes)
            or len(set(probes))!=len(probes) or type(budget) is not int or not 0<=budget<=100000):
            raise ValueError('invalid probes or byte budget')
        started=time.perf_counter(); cpu_started=time.process_time_ns()
        self.requests+=1
        attempts=3 if 'retry' in self.faults else 1
        durations=[]
        for _ in range(attempts):
            t=time.perf_counter();time.sleep(.006 if 'slow' in self.faults else .0012)
            durations.append((time.perf_counter()-t)*1000)
        if 'cpu' in self.faults:
            until=time.perf_counter()+.006
            while time.perf_counter()<until:pass
        price=99 if 'stale' in self.faults else 100
        elapsed=(time.perf_counter()-started)*1000
        service_cpu=time.process_time_ns()-cpu_started
        context={'stale':time.monotonic()-self.cache_written>60,'count':attempts,
                 'band':'slow' if max(durations)>3 else 'normal','alive':True,
                 'routes':['/checkout','/inventory']*20,
                 'authorization':SECRET,'nested':{'password':SECRET}}
        capture_started=time.process_time_ns(); frames=[]; emitted=0; skipped=[]
        for probe in probes:
            frame=allowed_frame(probe,context)
            size=len(encode(frame))
            if emitted+size>budget:
                skipped.append(probe);continue
            frames.append(frame);emitted+=size
        capture_cpu=time.process_time_ns()-capture_started
        return {'symptom':'anomaly' if price!=100 or elapsed>3.5 else 'normal',
                'elapsed_ms':elapsed,'service_cpu_ns':service_cpu,'capture_cpu_ns':capture_cpu,
                'frames':frames,'emitted_bytes':emitted,'skipped':skipped}

    def handler(self):
        service=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                status=200
                try:
                    if self.path!='/checkout':raise ValueError('unsupported endpoint')
                    length=int(self.headers.get('Content-Length',0))
                    if not 0<length<=4096:raise ValueError('request size')
                    data=json.loads(self.rfile.read(length))
                    if type(data) is not dict or set(data)!={'probes','budget'}:raise ValueError('request shape')
                    result=service.execute(data['probes'],data['budget'])
                except (ValueError,TypeError,KeyError,RecursionError):
                    status=400;result={'error':'invalid probe request'}
                raw=encode(result);self.send_response(status);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        return Handler

@contextmanager
def serve(service):
    server=ThreadingHTTPServer(('127.0.0.1',0),service.handler())
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join()

def request(url, probes=(), budget=0):
    body=encode({'probes':list(probes),'budget':budget})
    opener=build_opener(ProxyHandler({}))
    with opener.open(Request(url+'/checkout',data=body,headers={'Content-Type':'application/json'}),timeout=5) as response:
        return json.load(response)

# Authored causal signature assumptions, not production learned probabilities.
MODEL={'+'.join(names) or 'healthy':dict(zip(CORE,(stale,3 if retry else 1,'slow' if slow else 'normal')))
       for stale,slow,retry in itertools.product((False,True),repeat=3)
       for names in [[name for name,present in zip(('stale','slow','retry'),(stale,slow,retry)) if present]]}
KEY={'cache':'stale','attempts':'count','downstream':'band','heartbeat':'alive','context':'routes'}

def candidates(observed,symptom):
    return [name for name,signature in MODEL.items()
            if (name!='healthy' if symptom=='anomaly' else name=='healthy')
            and all(signature[p]==value for p,value in observed.items() if p in CORE)]

def choose(remaining,possible,costs):
    def score(probe):
        counts={}
        for name in possible:
            value=MODEL[name].get(probe,'constant');counts[str(value)]=counts.get(str(value),0)+1
        entropy=-sum((n/len(possible))*math.log2(n/len(possible)) for n in counts.values()) if possible else 0
        # Required signature verification wins over zero-information decorative probes.
        return (entropy/costs[probe],probe in CORE,-costs[probe],probe)
    return max(remaining,key=score)


def calibrate():
    observations=[];costs={p:0 for p in PROBES}
    for fault in FAULTS:
        with serve(Service(fault)) as url:
            result=request(url,PROBES,100000)
        observations.append({'fault_fixture':fault,**result})
        for frame in result['frames']:
            costs[frame['probe']]=max(costs[frame['probe']],len(encode(frame)))
    return {'max_measured_frame_bytes':costs,'observations':observations}


def diagnose(url, costs, *, budget=170, strategy='information', seed=7):
    if strategy not in ('information','cheapest','random','all'):raise ValueError('unknown strategy')
    if type(budget) is not int or budget<0:raise ValueError('invalid budget')
    initial=request(url);symptom=initial['symptom'];observed={};frames=[];runs=[initial]
    remaining=list(PROBES);spent=0;selection=[];rng=random.Random(seed)
    while remaining:
        possible=candidates(observed,symptom)
        affordable=[p for p in remaining if strategy=='all' or costs[p]<=budget-spent]
        if not affordable:break
        if strategy=='information':probe=choose(affordable,possible,costs)
        elif strategy=='cheapest':probe=min(affordable,key=lambda p:(costs[p],p))
        elif strategy=='random':probe=rng.choice(affordable)
        else:probe=affordable[0]
        remaining.remove(probe);selection.append(probe)
        run=request(url,[probe],100000 if strategy=='all' else budget-spent);runs.append(run)
        if run['symptom']!=symptom:
            # Timing jitter changed the initial evidence: no stable-incident diagnosis.
            symptom='unstable'
        spent+=run['emitted_bytes'];frames+=run['frames']
        for frame in run['frames']:
            p=frame['probe'];observed[p]=frame['values'][KEY[p]]
        if strategy=='information' and all(p in observed for p in CORE):break
    possible=candidates(observed,symptom) if symptom!='unstable' else []
    verified=all(p in observed for p in CORE)
    unique=possible[0] if len(possible)==1 else None
    identification=unique if verified and unique and '+' not in unique else None
    reason=('identified authored single-fault signature' if identification else
            'compound fault requires review' if unique and '+' in unique else
            'unmodeled/unstable evidence' if not possible else 'insufficient discrimination or budget')
    raw=b''.join(encode(frame) for frame in frames)
    return {'strategy':strategy,'budget':budget,'emitted_bytes':spent,'budget_exceeded':spent>budget,
            'selection':selection,'observed':observed,'candidates':possible,'diagnosis':identification,
            'abstained':identification is None,'reason':reason,'secret_absent':SECRET.encode() not in raw,
            'capture_cpu_ns':sum(r['capture_cpu_ns'] for r in runs),
            'service_cpu_ns':sum(r['service_cpu_ns'] for r in runs),
            'http_requests':len(runs),'elapsed_ms':sum(r['elapsed_ms'] for r in runs),'frames':frames}


def demo(seed=7):
    calibration=calibrate();costs=calibration['max_measured_frame_bytes'];rows=[]
    for fault in FAULTS:
        for strategy in ('information','cheapest','random','all'):
            with serve(Service(fault)) as url:
                result=diagnose(url,costs,budget=170,strategy=strategy,seed=seed)
            rows.append({'fault_fixture':fault,**result})
    summary={}
    for strategy in ('information','cheapest','random','all'):
        subset=[r for r in rows if r['strategy']==strategy]
        summary[strategy]={'cases':len(subset),'correct_single_faults':sum(r['diagnosis']==r['fault_fixture'] for r in subset if r['fault_fixture'] in ('healthy','stale','slow','retry')),
                           'adverse_control_abstentions':sum(r['abstained'] for r in subset if r['fault_fixture'] in ('dual','unmodeled')),
                           'emitted_bytes':sum(r['emitted_bytes'] for r in subset),'budget_violations':sum(r['budget_exceeded'] for r in subset)}
    return {'schema_version':1,'scope':'real local HTTP requests and probe capture; authored synthetic fault signatures; no Datadog adapter',
            'seed':seed,'budget_scope':'encoded newline JSON probe frames only; HTTP and fixed report overhead excluded',
            'calibration':calibration,'summary':summary,'runs':rows}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,default=7);p.add_argument('--output',type=Path);a=p.parse_args()
    text=json.dumps(demo(a.seed),indent=2)+'\n'
    if a.output:a.output.write_text(text)
    else:print(text,end='')
