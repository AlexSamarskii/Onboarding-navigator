import sys, os, pathlib, socket
base=pathlib.Path(sys.argv[1]); target=base/'workspace/telegram-rag-bot'
def guard(event,args):
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        p=pathlib.Path(os.fsdecode(args[0]))
        if any(x=='.env' or x.startswith('.env.') or x=='.idea' for x in p.parts):
            raise PermissionError('G0 prohibits sensitive file access')
        mode=args[1]
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(args[2],int) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        if writing and not p.resolve().is_relative_to(base/'.agent/artifacts'):
            raise PermissionError('G0 output must stay in artifacts')
    if event in ('socket.connect','socket.getaddrinfo'):
        raise PermissionError('G0 prohibits real network calls')
sys.addaudithook(guard)
sys.path.insert(0,str(target))
import pytest
args=['-p','no:cacheprovider','-p','pytest_asyncio.plugin','-o','asyncio_mode=auto','--rootdir',str(target), '--basetemp',str(base/'.agent/artifacts/g0_reaudit/pytest_temp'), '--junitxml',str(base/'.agent/artifacts/g0_reaudit/pytest_report.xml'),'--log-file',str(base/'.agent/artifacts/g0_reaudit/pytest_runtime.log'),'-q']
args += [str(p) for p in sorted((target/'tests').glob('test_*.py'))]
raise SystemExit(pytest.main(args))
