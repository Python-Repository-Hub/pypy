from pypy.jit.metainterp.history import LoopToken, ConstInt, History, Stats
from pypy.jit.metainterp.specnode import NotSpecNode, ConstantSpecNode
from pypy.jit.metainterp.compile import insert_loop_token, compile_new_loop
from pypy.jit.metainterp import optimize, jitprof, typesystem
from pypy.jit.metainterp.test.oparser import parse
from pypy.jit.metainterp.test.test_optimizefindnode import LLtypeMixin


def test_insert_loop_token():
    lst = []
    #
    tok1 = LoopToken()
    tok1.specnodes = [NotSpecNode()]
    insert_loop_token(lst, tok1)
    assert lst == [tok1]
    #
    tok2 = LoopToken()
    tok2.specnodes = [ConstantSpecNode(ConstInt(8))]
    insert_loop_token(lst, tok2)
    assert lst == [tok2, tok1]
    #
    tok3 = LoopToken()
    tok3.specnodes = [ConstantSpecNode(ConstInt(-13))]
    insert_loop_token(lst, tok3)
    assert lst == [tok2, tok3, tok1]


class FakeCPU:
    ts = typesystem.llhelper
    def __init__(self):
        self.seen = []
    def compile_loop(self, inputargs, operations, token):
        self.seen.append((inputargs, operations, token))

class FakeLogger:
    def log_loop(self, inputargs, operations):
        pass

class FakeState:
    optimize_loop = staticmethod(optimize.optimize_loop)
    debug_level = 0

class FakeMetaInterpStaticData:
    logger_noopt = FakeLogger()
    logger_ops = FakeLogger()

    state = FakeState()
    stats = Stats()
    profiler = jitprof.EmptyProfiler()
    def log(self, msg, event_kind=None):
        pass

class FakeMetaInterp:
    pass

def test_compile_new_loop():
    cpu = FakeCPU()
    staticdata = FakeMetaInterpStaticData()
    staticdata.cpu = cpu
    #
    loop = parse('''
    [p1]
    i1 = getfield_gc(p1, descr=valuedescr)
    i2 = int_add(i1, 1)
    p2 = new_with_vtable(ConstClass(node_vtable))
    setfield_gc(p2, i2, descr=valuedescr)
    jump(p2)
    ''', namespace=LLtypeMixin.__dict__.copy())
    #
    metainterp = FakeMetaInterp()
    metainterp.staticdata = staticdata
    metainterp.cpu = cpu
    metainterp.history = History(metainterp.cpu)
    metainterp.history.operations = loop.operations[:]
    metainterp.history.inputargs = loop.inputargs[:]
    #
    loop_tokens = []
    loop_token = compile_new_loop(metainterp, loop_tokens, [], 0)
    assert loop_tokens == [loop_token]
    #
    assert len(cpu.seen) == 1
    assert cpu.seen[0][2] == loop_token
    #
    del cpu.seen[:]
    metainterp = FakeMetaInterp()
    metainterp.staticdata = staticdata
    metainterp.cpu = cpu
    metainterp.history = History(metainterp.cpu)
    metainterp.history.operations = loop.operations[:]
    metainterp.history.inputargs = loop.inputargs[:]
    #
    loop_token_2 = compile_new_loop(metainterp, loop_tokens, [], 0)
    assert loop_token_2 is loop_token
    assert loop_tokens == [loop_token]
    assert len(cpu.seen) == 0
