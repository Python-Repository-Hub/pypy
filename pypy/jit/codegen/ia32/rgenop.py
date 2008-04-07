import sys, py, os
from pypy.rlib.objectmodel import specialize
from pypy.rpython.lltypesystem import lltype, llmemory, rffi
from pypy.jit.codegen.i386.ri386 import *
from pypy.jit.codegen.i386.codebuf import CodeBlockOverflow
from pypy.jit.codegen.model import AbstractRGenOp, GenLabel, GenBuilder
from pypy.jit.codegen.model import GenVar, GenConst, CodeGenSwitch
from pypy.rlib import objectmodel
from pypy.rpython.annlowlevel import llhelper
from pypy.jit.codegen.ia32.objmodel import IntVar, FloatVar, Var,\
     BoolVar, IntConst, AddrConst, BoolConst, FloatConst,\
     LL_TO_GENVAR, TOKEN_TO_SIZE, token_to_genvar, WORD, AddrVar
from pypy.jit.codegen.support import ctypes_mapping
from ctypes import cast, c_void_p, POINTER

DEBUG_CALL_ALIGN = True
if sys.platform == 'darwin':
    CALL_ALIGN = 4
else:
    CALL_ALIGN = 1

@specialize.arg(0)
def peek_value_at(T, addr):
    # now the Very Obscure Bit: when translated, 'addr' is an
    # address.  When not, it's an integer.  It just happens to
    # make the test pass, but that's probably going to change.
    if objectmodel.we_are_translated():
        if T is lltype.Float:
            return addr.float[0]
        elif T is llmemory.Address:
            return addr.address[0]
        elif isinstance(T, lltype.Ptr):
            return lltype.cast_int_to_ptr(T, addr.signed[0])
        else:
            return lltype.cast_primitive(T, addr.signed[0])
    else:
        tp = ctypes_mapping[T]
        p = cast(c_void_p(addr), POINTER(tp))
        return p[0]

@specialize.arg(0)
def poke_value_into(T, addr, value):
    # now the Very Obscure Bit: when translated, 'addr' is an
    # address.  When not, it's an integer.  It just happens to
    # make the test pass, but that's probably going to change.
    if objectmodel.we_are_translated():
        if T is lltype.Float:
            addr.float[0] = value
        elif isinstance(T, lltype.Ptr):
            addr.signed[0] = intmask(lltype.cast_ptr_to_int(value))
        elif T is llmemory.Address:
            addr.signed[0] = intmask(llmemory.cast_adr_to_int(value))
        else:
            addr.signed[0] = lltype.cast_primitive(lltype.Signed, value)
    else:
        tp = ctypes_mapping[T]
        p = cast(c_void_p(addr), POINTER(tp))
        p[0] = value

def map_arg(arg):
    # a small helper that provides correct type signature
    if isinstance(arg, lltype.Ptr):
        arg = llmemory.Address
    if isinstance(arg, (lltype.Array, lltype.Struct)):
        arg = lltype.Void
    return LL_TO_GENVAR[arg]

class Label(GenLabel):

    def __init__(self, startaddr, arg_positions, stackdepth):
        self.startaddr = startaddr
        self.arg_positions = arg_positions
        self.stackdepth = stackdepth


class FlexSwitch(CodeGenSwitch):

    def __init__(self, rgenop):
        self.rgenop = rgenop
        self.default_case_builder = None
        self.default_case_key = 0
        self._je_key = 0

    def initialize(self, builder, gv_exitswitch):
        mc = builder.mc
        mc.MOV(eax, gv_exitswitch.operand(builder))
        self.saved_state = builder._save_state()
        self._reserve(mc)

    def _reserve(self, mc):
        RESERVED = 11*4+5      # XXX quite a lot for now :-/
        pos = mc.tell()
        mc.UD2()
        mc.write('\x00' * (RESERVED-1))
        self.nextfreepos = pos
        self.endfreepos = pos + RESERVED

    def _reserve_more(self):
        start = self.nextfreepos
        end   = self.endfreepos
        newmc = self.rgenop.open_mc()
        self._reserve(newmc)
        self.rgenop.close_mc(newmc)
        fullmc = self.rgenop.InMemoryCodeBuilder(start, end)
        fullmc.JMP(rel32(self.nextfreepos))
        fullmc.done()
        
    def add_case(self, gv_case):
        rgenop = self.rgenop
        targetbuilder = Builder._new_from_state(rgenop, self.saved_state)
        try:
            self._add_case(gv_case, targetbuilder)
        except CodeBlockOverflow:
            self._reserve_more()
            self._add_case(gv_case, targetbuilder)
        targetbuilder._open()
        return targetbuilder
    
    def _add_case(self, gv_case, targetbuilder):
        start = self.nextfreepos
        end   = self.endfreepos
        mc = self.rgenop.InMemoryCodeBuilder(start, end)
        mc.CMP(eax, gv_case.operand(None))
        self._je_key = targetbuilder.come_from(mc, 'JE', self._je_key)
        pos = mc.tell()
        assert self.default_case_builder
        self.default_case_key = self.default_case_builder.come_from(
            mc, 'JMP', self.default_case_key)
        mc.done()
        self._je_key = 0
        self.nextfreepos = pos

    def _add_default(self):
        rgenop = self.rgenop
        targetbuilder = Builder._new_from_state(rgenop, self.saved_state)
        self.default_case_builder = targetbuilder
        start = self.nextfreepos
        end   = self.endfreepos
        mc = self.rgenop.InMemoryCodeBuilder(start, end)
        self.default_case_key = targetbuilder.come_from(mc, 'JMP')
        targetbuilder._open()
        return targetbuilder

def _create_ovf_one_version(opname, flag):
    def op_ovf(self, gv_x):
        gv = getattr(self, opname)(gv_x)
        getattr(self.mc, 'SET' + flag)(al)
        return gv, self.returnboolvar(al)
    op_ovf.func_name = opname + '_ovf'
    return op_ovf

def _create_ovf_two_version(opname, flag):
    def op_ovf(self, gv_x, gv_y):
        gv = getattr(self, opname)(gv_x, gv_y)
        getattr(self.mc, 'SET' + flag)(al)
        return gv, self.returnboolvar(al)
    op_ovf.func_name = opname + '_ovf'
    return op_ovf

class Builder(GenBuilder):

    def __init__(self, rgenop, stackdepth):
        self.rgenop = rgenop
        self.stackdepth = stackdepth
        self.mc = None
        self._pending_come_from = {}
        self.start = 0
        self.closed = False
        self.tail = (0, 0)

    def _open(self):
        if self.mc is None and not self.closed:
            self.mc = self.rgenop.open_mc()
            if not self.start:
                # This is the first open. remember the start address
                # and patch all come froms.
                self.start = self.mc.tell()
                come_froms = self._pending_come_from
                self._pending_come_from = None
                for start, (end, insn) in come_froms.iteritems():
                    if end == self.start:
                        # there was a pending JMP just before self.start,
                        # so we can as well overwrite the JMP and start writing
                        # code directly there
                        self.mc.seekback(end - start)
                        self.start = start
                        break
                for start, (end, insn) in come_froms.iteritems():
                    if start != self.start:
                        mc = self.rgenop.InMemoryCodeBuilder(start, end)
                        self._emit_come_from(mc, insn, self.start)
                        mc.done()
            else:
                # We have been paused and are being opened again.
                # Is the new codeblock immediately after the previous one?
                prevstart, prevend = self.tail
                curpos = self.mc.tell()
                if prevend == curpos:
                    # Yes. We can overwrite the JMP and just continue writing
                    # code directly there
                    self.mc.seekback(prevend - prevstart)
                else:
                    # No. Patch the jump at the end of the previous codeblock.
                    mc = self.rgenop.InMemoryCodeBuilder(prevstart, prevend)
                    mc.JMP(rel32(curpos))
                    mc.done()

    def pause_writing(self, alive_vars_gv):
        if self.mc is not None:
            start = self.mc.tell()
            self.mc.JMP(rel32(0))
            end = self.mc.tell()
            self.tail = (start, end)
            self.mc.done()
            self.rgenop.close_mc(self.mc)
            self.mc = None
        return self
        
    def start_writing(self):
        self._open()
        
    def _emit_come_from(self, mc, insn, addr):
        if insn == 'JMP':
            mc.JMP(rel32(addr))
        elif insn == 'JE':
            mc.JE(rel32(addr))
        elif insn == 'JNE':
            mc.JNE(rel32(addr))
        else:
            raise ValueError('Unsupported jump')
        
    def come_from(self, mc, insn, key=0):
        start = mc.tell()
        if self._pending_come_from is None:
            self._emit_come_from(mc, insn, self.start)
        else:
            self._emit_come_from(mc, insn, 0)
            end = mc.tell()
            if key != 0:
                del self._pending_come_from[key]
            self._pending_come_from[start] = (end, insn)
        return start
    
    def end(self):
        pass

    def _write_prologue(self, arg_tokens):
        self._open()
        #self.mc.BREAKPOINT()
        # self.stackdepth-1 is the return address; the arguments
        # come just before
        n = 0
        result = []
        for arg in arg_tokens:
            arg_gv = token_to_genvar(arg, self.stackdepth-2-n)
            n += arg_gv.SIZE
            result.append(arg_gv)
        return result

    def _close(self):
        self.closed = True
        self.mc.done()
        self.rgenop.close_mc(self.mc)
        self.mc = None

    def _fork(self):
        return self.rgenop.newbuilder(self.stackdepth)

    def _save_state(self):
        return self.stackdepth

    @staticmethod
    def _new_from_state(rgenop, stackdepth):
        return rgenop.newbuilder(stackdepth)

    @specialize.arg(1)
    def genop1(self, opname, gv_arg):
        genmethod = getattr(self, 'op_' + opname)
        return genmethod(gv_arg)

    @specialize.arg(1)
    def genop2(self, opname, gv_arg1, gv_arg2):
        genmethod = getattr(self, 'op_' + opname)
        return genmethod(gv_arg1, gv_arg2)

    @specialize.arg(1)
    def genraisingop2(self, opname, gv_arg1, gv_arg2):
        genmethod = getattr(self, 'op_' + opname)
        return genmethod(gv_arg1, gv_arg2)

    @specialize.arg(1)
    def genraisingop1(self, opname, gv_arg):
        genmethod = getattr(self, 'op_' + opname)
        return genmethod(gv_arg)

    def genop_getfield(self, (offset, fieldsize, kindtoken), gv_ptr):
        self.mc.MOV(edx, gv_ptr.operand(self))
        return self.newvarfromaddr(kindtoken, (edx, None, 0, offset),
                                   fieldsize)
        
        if fieldsize == WORD:
            op = mem(edx, offset)
        else:
            if fieldsize == 1:
                op = mem8(edx, offset)
            elif fieldsize == 2:
                op = mem(edx, offset)
            else:
                raise NotImplementedError("fieldsize != 1,2,4")
            self.mc.MOVZX(eax, op)
            op = eax
        return self.returnintvar(op)

    def genop_get_frame_base(self):
        self.mc.MOV(eax, esp)
        self.mc.ADD(eax, imm((self.stackdepth - 1) * WORD))
        return self.returnintvar(eax)

    def get_frame_info(self, vars_gv):
        return vars_gv

    def genop_setfield(self, (offset, fieldsize, kt), gv_ptr, gv_value):
        assert fieldsize != 2
        self.mc.MOV(edx, gv_ptr.operand(self))
        gv_value.movetonewaddr(self, (edx, None, 0, offset))

    def genop_getsubstruct(self, (offset, fieldsize, kt), gv_ptr):
        self.mc.MOV(edx, gv_ptr.operand(self))
        self.mc.LEA(eax, mem(edx, offset))
        return self.returnintvar(eax)

    def _compute_itemaddr(self, base, arraytoken, gv_index):
        lengthoffset, startoffset, itemoffset, _ = arraytoken
        if isinstance(gv_index, IntConst):
            startoffset += itemoffset * gv_index.value
            return (base, None, 0, startoffset)
        elif itemoffset in SIZE2SHIFT:
            self.mc.MOV(ecx, gv_index.operand(self))
            return (base, ecx, SIZE2SHIFT[itemoffset], startoffset)
        else:
            self.mc.IMUL(ecx, gv_index.operand(self), imm(itemoffset))
            return (base, ecx, 0, startoffset)
        
    def itemaddr(self, base, arraytoken, gv_index):
        # uses ecx
        lengthoffset, startoffset, itemoffset, _ = arraytoken
        addr = self._compute_itemaddr(base, arraytoken, gv_index)
        if itemoffset == 1:
            return self.mem_access8(addr)
        else:
            return self.mem_access(addr)

    def mem_access(self, addr, addofs=0):
        base, reg, shift, ofs = addr
        return memSIB(base, reg, shift, ofs + addofs)

    def mem_access8(self, addr, addofs=0):
        base, reg, shift, ofs = addr
        return memSIB8(base, reg, shift, ofs + addofs)

    def genop_getarrayitem(self, arraytoken, gv_ptr, gv_index):
        self.mc.MOV(edx, gv_ptr.operand(self))
        _, _, itemsize, kindtoken = arraytoken
        addr = self._compute_itemaddr(edx, arraytoken, gv_index)
        return self.newvarfromaddr(kindtoken, addr, itemsize)

    def genop_getarraysubstruct(self, arraytoken, gv_ptr, gv_index):
        self.mc.MOV(edx, gv_ptr.operand(self))
        op = self.itemaddr(edx, arraytoken, gv_index)
        self.mc.LEA(eax, op)
        return self.returnintvar(eax)

    def genop_getarraysize(self, arraytoken, gv_ptr):
        lengthoffset, startoffset, itemoffset, _ = arraytoken
        self.mc.MOV(edx, gv_ptr.operand(self))
        return self.returnintvar(mem(edx, lengthoffset))

    def genop_setarrayitem(self, arraytoken, gv_ptr, gv_index, gv_value):
        itemsize = arraytoken[2]
        self.mc.MOV(edx, gv_ptr.operand(self))
        destaddr = self._compute_itemaddr(edx, arraytoken, gv_index)
        assert itemsize != 2
        gv_value.movetonewaddr(self, destaddr)
        #if itemsize <= WORD:
        #    self.mc.MOV(eax, gv_value.operand(self))
        #    if itemsize != WORD:
        #        if itemsize == 1:
        #            self.mc.MOV(destop, al)
        #            return
        #        elif itemsize == 2:
        #            self.mc.o16()    # followed by the MOV below
        #            ^^^^^^^^^^^^^ [fijal] what's this for?
        #        else:
        #            raise NotImplementedError("setarrayitme for fieldsize == 3")
        #    self.mc.MOV(destop, eax)
        #else:    
        #    self.move_bigger_value(destop, gv_value, itemsize)

    def genop_malloc_fixedsize(self, size):
        # XXX boehm only, no atomic/non atomic distinction for now
        self.push(imm(size))
        self.mc.CALL(rel32(gc_malloc_fnaddr()))
        return self.returnintvar(eax)

    def genop_malloc_varsize(self, varsizealloctoken, gv_size):
        # XXX boehm only, no atomic/non atomic distinction for now
        # XXX no overflow checking for now
        op_size = self.itemaddr(None, varsizealloctoken, gv_size)
        self.mc.LEA(edx, op_size)
        self.push(edx)
        self.mc.CALL(rel32(gc_malloc_fnaddr()))
        lengthoffset = varsizealloctoken[0]
        self.mc.MOV(ecx, gv_size.operand(self))
        self.mc.MOV(mem(eax, lengthoffset), ecx)
        return self.returnintvar(eax)
        
    def genop_call(self, sigtoken, gv_fnptr, args_gv):
        numargs = len(sigtoken[0])
        MASK = CALL_ALIGN-1
        if MASK:
            final_depth = self.stackdepth + numargs
            delta = ((final_depth+MASK)&~MASK)-final_depth
            if delta:
                self.mc.SUB(esp, imm(delta*WORD))
                self.stackdepth += delta
        for i in range(numargs-1, -1, -1):
            args_gv[i].newvar(self)
        if DEBUG_CALL_ALIGN:
            self.mc.MOV(eax, esp)
            self.mc.AND(eax, imm8((WORD*CALL_ALIGN)-1))
            self.mc.ADD(eax, imm32(sys.maxint))   # overflows unless eax == 0
            self.mc.INTO()
        if gv_fnptr.is_const:
            target = gv_fnptr.revealconst(lltype.Signed)
            self.mc.CALL(rel32(target))
        else:
            self.mc.CALL(gv_fnptr.operand(self))
        # XXX implement different calling conventions and different types
        RESULT = sigtoken[1]
        if RESULT == "f":
            return self.returnfloatvar(st0)
        return self.returnintvar(eax)

    def genop_same_as(self, gv_x):
        if gv_x.is_const:    # must always return a var
            return gv_x.newvar(self)
        else:
            return gv_x

    def genop_debug_pdb(self):    # may take an args_gv later
        self.mc.BREAKPOINT()

    def genop_cast_int_to_ptr(self, kind, gv_int):
        return gv_int     # identity

    def enter_next_block(self, args_gv):
        self._open()
        arg_positions = []
        seen = {}
        for i in range(len(args_gv)):
            gv = args_gv[i]
            # turn constants into variables; also make copies of vars that
            # are duplicate in args_gv
            if not isinstance(gv, Var) or gv.stackpos in seen:
                gv = args_gv[i] = gv.newvar(self)
            # remember the var's position in the stack
            assert gv.stackpos >= 0
            arg_positions.append(gv.stackpos)
            seen[gv.stackpos] = None
        for pos in arg_positions:
            assert pos >= 0
        return Label(self.mc.tell(), arg_positions, self.stackdepth)

    def jump_if_false(self, gv_condition, args_gv):
        targetbuilder = self._fork()
        self.mc.CMP(gv_condition.operand(self), imm8(0))
        targetbuilder.come_from(self.mc, 'JE')
        return targetbuilder

    def jump_if_true(self, gv_condition, args_gv):
        targetbuilder = self._fork()
        self.mc.CMP(gv_condition.operand(self), imm8(0))
        targetbuilder.come_from(self.mc, 'JNE')
        return targetbuilder

    def finish_and_return(self, sigtoken, gv_returnvar):
        self._open()
        stackdepth = self.rgenop._compute_stack_depth(sigtoken)
        initialstackdepth = self.rgenop._initial_stack_depth(stackdepth)
        if isinstance(gv_returnvar, FloatVar) or isinstance(gv_returnvar, FloatConst):
            self.mc.FLDL(gv_returnvar.operand(self))
        elif gv_returnvar is not None:
            self.mc.MOV(eax, gv_returnvar.operand(self))
        self.mc.ADD(esp, imm(WORD * (self.stackdepth - initialstackdepth)))
        self.mc.RET()
        self._close()

    def finish_and_goto(self, outputargs_gv, target):
        self._open()
        remap_stack_layout(self, outputargs_gv, target)
        self.mc.JMP(rel32(target.startaddr))
        self._close()

    def flexswitch(self, gv_exitswitch, args_gv):
        result = FlexSwitch(self.rgenop)
        result.initialize(self, gv_exitswitch)
        self._close()
        return result, result._add_default()

    def show_incremental_progress(self):
        pass

    def log(self, msg):
        self.mc.log(msg)

    # ____________________________________________________________

    def stack_access(self, stackpos):
        return mem(esp, WORD * (self.stackdepth - 1 - stackpos))

    def stack_access64(self, stackpos):
        return mem64(esp, WORD * (self.stackdepth - 1 - stackpos))

    def push(self, op):
        self.mc.PUSH(op)
        self.stackdepth += 1

    def pushfloatfromst0(self, op):
        self.mc.SUB(esp, imm(WORD * FloatVar.SIZE))
        self.stackdepth += 2
        self.mc.FSTPL(op.operand(self))

    def returnintvar(self, op):
        res = IntVar(self.stackdepth)
        if op is None:
            self.push(imm(0))
        else:
            self.push(op)
        return res

    def returnaddrvar(self, op):
        res = AddrVar(self.stackdepth)
        if op is None:
            self.push(imm(0))
        else:
            self.push(op)
        return res

    def returnboolvar(self, op):
        if op is eax:
            pass
        elif isinstance(op, IMM8):
            self.mc.MOV(eax, op)
        else:
            self.mc.MOVZX(eax, op)
        res = BoolVar(self.stackdepth)
        self.push(eax)
        return res

    def returnfloatvar(self, op):
        res = FloatVar(self.stackdepth + 1)
        if op is st0:
            self.pushfloatfromst0(res)
        elif op is None:
            self.push(imm(0))
            self.push(imm(0))
        else:
            raise NotImplementedError("Return float var not on fp stack")
        return res

    def newvarfromaddr(self, kindtoken, addr, size):
        # XXX probably we can still do something here with unrolling
        #     iterable, but let's not be too smart...
        if kindtoken == 'i':
            # XXX kind of a hack
            if size == 1:
                self.mc.MOVZX(eax, self.mem_access8(addr))
                return self.returnintvar(eax)
            elif size == 2:
                # XXX never tested
                self.mc.MOV(eax, self.mem_access(addr))
                self.mc.o16()
                return self.returnintvar(eax)
            return self.returnintvar(self.mem_access(addr))
        elif kindtoken == 'a':
            return self.returnaddrvar(self.mem_access(addr))
        elif kindtoken == 'b':
            return self.returnboolvar(self.mem_access(addr))
        elif kindtoken == 'f':
            return self.newfloatfrommem(addr)
        else:
            raise NotImplementedError("Return var of kind %s" % (kindtoken,))

    def newvar(self, kindtoken):
        if kindtoken == 'i':
            return self.returnintvar(None)
        elif kindtoken == 'a':
            return self.returnaddrvar(None)
        elif kindtoken == 'b':
            return self.returnboolvar(None)
        elif kindtoken == 'f':
            return self.returnfloatvar(None)
        else:
            raise NotImplementedError("Return var of kind %s" % (kindtoken,))
    
    def newfloatfrommem(self, (base, reg, shift, ofs)):
        res = FloatVar(self.stackdepth + 1)
        self.mc.PUSH(memSIB(base, reg, shift, ofs + WORD))
        # XXX pom pom pom, stupid hack
        if base is esp:
            self.mc.PUSH(memSIB(base, reg, shift, ofs + WORD))
        else:
            self.mc.PUSH(memSIB(base, reg, shift, ofs))
        self.stackdepth += 2
        return res

    @staticmethod
    def identity(gv_x):
        return gv_x

    def op_int_is_true(self, gv_x):
        self.mc.CMP(gv_x.operand(self), imm8(0))
        self.mc.SETNE(al)
        return self.returnboolvar(al)

    def op_ptr_iszero(self, gv_x):
        self.mc.CMP(gv_x.operand(self), imm8(0))
        self.mc.SETE(al)
        return self.returnboolvar(al)

    def op_int_add(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.ADD(eax, gv_y.operand(self))
        return self.returnintvar(eax)

    op_int_add_ovf = _create_ovf_two_version('op_int_add', 'O')

    def op_int_sub(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.SUB(eax, gv_y.operand(self))
        return self.returnintvar(eax)

    op_int_sub_ovf = _create_ovf_two_version('op_int_sub', 'O')

    def op_int_mul(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.IMUL(eax, gv_y.operand(self))
        return self.returnintvar(eax)

    op_int_mul_ovf = _create_ovf_two_version('op_int_mul', 'O')

    def op_int_floordiv(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CDQ()
        self.mc.IDIV(gv_y.nonimmoperand(self, ecx))
        return self.returnintvar(eax)

    def op_int_mod(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CDQ()
        self.mc.IDIV(gv_y.nonimmoperand(self, ecx))
        return self.returnintvar(edx)

    def op_int_and(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.AND(eax, gv_y.operand(self))
        return self.returnintvar(eax)

    def op_int_or(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.OR(eax, gv_y.operand(self))
        return self.returnintvar(eax)

    def op_int_xor(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.XOR(eax, gv_y.operand(self))
        return self.returnintvar(eax)

    def op_int_lt(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETL(al)
        return self.returnboolvar(al)

    def op_int_le(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETLE(al)
        return self.returnboolvar(al)

    def op_int_eq(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETE(al)
        return self.returnboolvar(al)

    def op_int_ne(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETNE(al)
        return self.returnboolvar(al)

    def op_int_gt(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETG(al)
        return self.returnboolvar(al)

    def op_int_ge(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETGE(al)
        return self.returnboolvar(al)

    def op_int_neg(self, gv_x):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.NEG(eax)
        return self.returnintvar(eax)

    op_int_neg_ovf = _create_ovf_one_version('op_int_neg', 'O')

    def op_int_abs(self, gv_x):
        # XXX cannot we employ fp unit to do that for us? :)
        self.mc.MOV(eax, gv_x.operand(self))
        # ABS-computing code from Psyco, found by exhaustive search
        # on *all* short sequences of operations :-)
        self.mc.ADD(eax, eax)
        self.mc.SBB(eax, gv_x.operand(self))
        self.mc.SBB(edx, edx)
        self.mc.XOR(eax, edx)
        return self.returnintvar(eax)

    op_int_abs_ovf = _create_ovf_one_version('op_int_abs', 'L')

    def op_int_invert(self, gv_x):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.NOT(eax)
        return self.returnintvar(eax)

    def op_int_lshift(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.MOV(ecx, gv_y.operand(self))
        self.mc.SHL(eax, cl)
        self.mc.CMP(ecx, imm8(32))
        self.mc.SBB(ecx, ecx)
        self.mc.AND(eax, ecx)
        return self.returnintvar(eax)

    def op_int_rshift(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.MOV(ecx, imm8(31))
        if isinstance(gv_y, IntConst):
            intval = gv_y.value
            if intval < 0 or intval > 31:
                intval = 31
            self.mc.MOV(cl, imm8(intval))
        else:
            op2 = gv_y.operand(self)
            self.mc.CMP(op2, ecx)
            self.mc.CMOVBE(ecx, op2)
        self.mc.SAR(eax, cl)
        return self.returnintvar(eax)

    op_uint_is_true = op_int_is_true
    op_uint_invert  = op_int_invert
    op_uint_add     = op_int_add
    op_uint_sub     = op_int_sub

    def op_uint_mul(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.MUL(gv_y.nonimmoperand(self, edx))
        return self.returnintvar(eax)

    def op_uint_floordiv(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.XOR(edx, edx)
        self.mc.DIV(gv_y.nonimmoperand(self, ecx))
        return self.returnintvar(eax)

    def op_uint_mod(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.XOR(edx, edx)
        self.mc.DIV(gv_y.nonimmoperand(self, ecx))
        return self.returnintvar(edx)

    def op_uint_lt(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETB(al)
        return self.returnboolvar(al)

    def op_uint_le(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETBE(al)
        return self.returnboolvar(al)

    op_uint_eq = op_int_eq
    op_uint_ne = op_int_ne

    def op_uint_gt(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETA(al)
        return self.returnboolvar(al)

    def op_uint_ge(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.CMP(eax, gv_y.operand(self))
        self.mc.SETAE(al)
        return self.returnboolvar(al)

    op_uint_and    = op_int_and
    op_uint_or     = op_int_or
    op_uint_xor    = op_int_xor
    op_uint_lshift = op_int_lshift

    def op_uint_rshift(self, gv_x, gv_y):
        self.mc.MOV(eax, gv_x.operand(self))
        self.mc.MOV(ecx, gv_y.operand(self))
        self.mc.SHR(eax, cl)
        self.mc.CMP(ecx, imm8(32))
        self.mc.SBB(ecx, ecx)
        self.mc.AND(eax, ecx)
        return self.returnintvar(eax)

    def op_bool_not(self, gv_x):
        self.mc.CMP(gv_x.operand(self), imm8(0))
        self.mc.SETE(al)
        return self.returnboolvar(al)

    def op_cast_bool_to_int(self, gv_x):
        self.mc.MOVZX(eax, gv_x.operand(self))
        return self.returnintvar(eax)

    op_cast_bool_to_uint   = op_cast_bool_to_int

    op_cast_char_to_int    = identity
    op_cast_unichar_to_int = identity
    op_cast_int_to_char    = identity
    op_cast_int_to_unichar = identity
    op_cast_int_to_uint    = identity
    op_cast_uint_to_int    = identity
    op_cast_ptr_to_int     = identity
    op_cast_int_to_ptr     = identity

    op_char_lt = op_int_lt
    op_char_le = op_int_le
    op_char_eq = op_int_eq
    op_char_ne = op_int_ne
    op_char_gt = op_int_gt
    op_char_ge = op_int_ge

    op_unichar_eq = op_int_eq
    op_unichar_ne = op_int_ne

    op_ptr_nonzero = op_int_is_true
    op_ptr_eq      = op_int_eq
    op_ptr_ne      = op_int_ne

    def op_float_add(self, gv_x, gv_y):
        self.mc.FLDL(gv_y.operand(self))
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FADDP()
        return self.returnfloatvar(st0)

    def op_float_sub(self, gv_x, gv_y):
        self.mc.FLDL(gv_y.operand(self))
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FSUBP()
        return self.returnfloatvar(st0)

    def op_float_mul(self, gv_x, gv_y):
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FLDL(gv_y.operand(self))
        self.mc.FMULP()
        return self.returnfloatvar(st0)

    def op_float_truediv(self, gv_x, gv_y):
        self.mc.FLDL(gv_y.operand(self))
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FDIVP()
        return self.returnfloatvar(st0)

    def op_float_neg(self, gv_x):
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FCHS()
        return self.returnfloatvar(st0)

    def op_float_abs(self, gv_x):
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FABS()
        return self.returnfloatvar(st0)

    def op_float_is_true(self, gv_x):
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FTST()
        self.mc.FNSTSW()
        self.mc.SAHF()
        self.mc.SETNZ(al)
        return self.returnboolvar(al)

    def _load_float_ctword(self, gv_x, gv_y):
        self.mc.FLDL(gv_x.operand(self))
        self.mc.FLDL(gv_y.operand(self))
        self.mc.FUCOMPP()
        self.mc.FNSTSW()        

    @specialize.arg(3)
    def _float_compare(self, gv_x, gv_y, immval):
        self._load_float_ctword(gv_x, gv_y)
        self.mc.TEST(ah, imm8(immval))
        self.mc.SETE(al)
        return self.returnboolvar(al)

    def op_float_lt(self, gv_x, gv_y):
        return self._float_compare(gv_x, gv_y, 69)
        
    def op_float_le(self, gv_x, gv_y):
        return self._float_compare(gv_x, gv_y, 5)

    def op_float_eq(self, gv_x, gv_y):
        self._load_float_ctword(gv_x, gv_y)
        self.mc.SAHF()
        self.mc.SETE(al)
        self.mc.SETNP(dl)
        self.mc.AND(edx, eax)
        return self.returnboolvar(al)

    def op_float_ne(self, gv_x, gv_y):
        self._load_float_ctword(gv_x, gv_y)
        self.mc.SAHF()
        self.mc.SETNE(al)
        self.mc.SETP(dl)
        self.mc.OR(edx, eax)
        return self.returnboolvar(al)

    def op_float_gt(self, gv_x, gv_y):
        return self._float_compare(gv_y, gv_x, 69)

    def op_float_ge(self, gv_x, gv_y):
        return self._float_compare(gv_y, gv_x, 5)

    def op_cast_float_to_int(self, gv_x):
        # XXX gcc is also checking something in control word
        self.mc.FLDL(gv_x.operand(self))
        self.mc.SUB(esp, imm(WORD))
        self.stackdepth += 1
        res = IntVar(self.stackdepth)
        self.mc.FISTP(res.operand(self))
        return res

    def op_cast_int_to_float(self, gv_x):
        # XXX gcc is also checking something in control word
        self.mc.FILD(gv_x.operand(self))
        return self.returnfloatvar(st0)

    def alloc_frame_place(self, kind, gv_initial_value=None):
        if gv_initial_value is not None:
            return gv_initial_value.newvar(self)
        return self.newvar(kind)

    def genop_absorb_place(self, v):
        return v

SIZE2SHIFT = {1: 0,
              2: 1,
              4: 2,
              8: 3}

GC_MALLOC = lltype.Ptr(lltype.FuncType([lltype.Signed], llmemory.Address))

def gc_malloc(size):
    from pypy.rpython.lltypesystem.lloperation import llop
    return llop.call_boehm_gc_alloc(llmemory.Address, size)

def gc_malloc_fnaddr():
    """Returns the address of the Boehm 'malloc' function."""
    if objectmodel.we_are_translated():
        gc_malloc_ptr = llhelper(GC_MALLOC, gc_malloc)
        return lltype.cast_ptr_to_int(gc_malloc_ptr)
    else:
        # <pedronis> don't do this at home
        import threading
        if not isinstance(threading.currentThread(), threading._MainThread):
            import py
            py.test.skip("must run in the main thread")
        try:
            import ctypes
            from ctypes import cast, c_void_p, util
            path = util.find_library('gc')
            if path is None:
                raise ImportError("Boehm (libgc) not found")
            boehmlib = ctypes.cdll.LoadLibrary(path)
        except ImportError, e:
            import py
            py.test.skip(str(e))
        else:
            GC_malloc = boehmlib.GC_malloc
            return cast(GC_malloc, c_void_p).value

# ____________________________________________________________

def _remap_bigger_values(args_gv, arg_positions):
    """ This function cheats and changes all FloatVars into double
    IntVars. This might be probably optimized in some way in order
    to provide greater performance, but should be enough for now
    """
    res_gv = []
    res_positions = []
    for i in range(len(args_gv)):
        gv = args_gv[i]
        pos = arg_positions[i]
        if gv.SIZE == 1:
            res_gv.append(gv)
            res_positions.append(pos)
        else:
            assert gv.SIZE == 2
            if isinstance(gv, FloatVar):
                res_gv.append(IntVar(gv.stackpos))
                res_gv.append(IntVar(gv.stackpos - 1))
            else:
                assert isinstance(gv, FloatConst)
                buf = rffi.cast(rffi.INTP, gv._compute_addr())
                res_gv.append(IntConst(buf[0]))
                res_gv.append(IntConst(buf[1]))
            res_positions.append(pos)
            res_positions.append(pos - 1)    
    # no repeats please
    all = {}
    for key in res_positions:
        assert key not in all
        all[key] = True
    #if not objectmodel.we_are_translated():
    #    assert sorted(dict.fromkeys(res_positions).keys()) == sorted(res_positions)
    return res_gv, res_positions

def remap_stack_layout(builder, outputargs_gv, target):
##    import os
##    s = ', '.join([gv.repr() for gv in outputargs_gv])
##    os.write(2, "writing at %d (stack=%d, [%s])\n  --> %d (stack=%d, %s)\n"
##     % (builder.mc.tell(),
##        builder.stackdepth,
##        s,
##        target.startaddr,
##        target.stackdepth,
##        target.arg_positions))

    N = target.stackdepth
    if builder.stackdepth < N:
        builder.mc.SUB(esp, imm(WORD * (N - builder.stackdepth)))
        builder.stackdepth = N
        
    for pos in target.arg_positions:
        assert pos >= 0
    outputargs_gv, arg_positions = _remap_bigger_values(outputargs_gv,
                                                        target.arg_positions)
    for pos in arg_positions:
        assert pos >= 0

    M = len(outputargs_gv)
    assert M == len(arg_positions)
    targetlayout = [None] * N
    srccount = [-N] * N
    for i in range(M):
        pos = arg_positions[i]
        gv = outputargs_gv[i]
        assert targetlayout[pos] is None
        targetlayout[pos] = gv
        srccount[pos] = 0
    pending_dests = M
    for i in range(M):
        targetpos = arg_positions[i]
        gv = outputargs_gv[i]
        if isinstance(gv, Var):
            p = gv.stackpos
            if 0 <= p < N:
                if p == targetpos:
                    srccount[p] = -N     # ignore 'v=v'
                    pending_dests -= 1
                else:
                    srccount[p] += 1

    while pending_dests:
        progress = False
        for i in range(N):
            if srccount[i] == 0:
                srccount[i] = -1
                pending_dests -= 1
                gv_src = targetlayout[i]
                if isinstance(gv_src, Var):
                    p = gv_src.stackpos
                    if 0 <= p < N:
                        srccount[p] -= 1
                builder.mc.MOV(eax, gv_src.operand(builder))
                builder.mc.MOV(builder.stack_access(i), eax)
                progress = True
        if not progress:
            # we are left with only pure disjoint cycles; break them
            for i in range(N):
                if srccount[i] >= 0:
                    dst = i
                    builder.mc.MOV(edx, builder.stack_access(dst))
                    while True:
                        assert srccount[dst] == 1
                        srccount[dst] = -1
                        pending_dests -= 1
                        gv_src = targetlayout[dst]
                        assert isinstance(gv_src, Var)
                        src = gv_src.stackpos
                        assert 0 <= src < N
                        if src == i:
                            break
                        builder.mc.MOV(eax, builder.stack_access(src))
                        builder.mc.MOV(builder.stack_access(dst), eax)
                        dst = src
                    builder.mc.MOV(builder.stack_access(dst), edx)
            assert pending_dests == 0

    if builder.stackdepth > N:
        builder.mc.ADD(esp, imm(WORD * (builder.stackdepth - N)))
        builder.stackdepth = N


#

dummy_var = Var(0)

class ReplayFlexSwitch(CodeGenSwitch):

    def __init__(self, replay_builder):
        self.replay_builder = replay_builder

    def add_case(self, gv_case):
        return self.replay_builder

class ReplayBuilder(GenBuilder):

    def __init__(self, rgenop):
        self.rgenop = rgenop

    def end(self):
        pass

    @specialize.arg(1)
    def genop1(self, opname, gv_arg):
        return dummy_var

    @specialize.arg(1)
    def genop2(self, opname, gv_arg1, gv_arg2):
        return dummy_var

    def genop_getfield(self, fieldtoken, gv_ptr):
        return dummy_var

    def genop_setfield(self, fieldtoken, gv_ptr, gv_value):
        return dummy_var

    def genop_getsubstruct(self, fieldtoken, gv_ptr):
        return dummy_var

    def genop_getarrayitem(self, arraytoken, gv_ptr, gv_index):
        return dummy_var

    def genop_getarraysubstruct(self, arraytoken, gv_ptr, gv_index):
        return dummy_var

    def genop_getarraysize(self, arraytoken, gv_ptr):
        return dummy_var

    def genop_setarrayitem(self, arraytoken, gv_ptr, gv_index, gv_value):
        return dummy_var

    def genop_malloc_fixedsize(self, size):
        return dummy_var

    def genop_malloc_varsize(self, varsizealloctoken, gv_size):
        return dummy_var
        
    def genop_call(self, sigtoken, gv_fnptr, args_gv):
        return dummy_var

    def genop_same_as(self, gv_x):
        return dummy_var

    def genop_debug_pdb(self):    # may take an args_gv later
        pass

    def enter_next_block(self, args_gv):
        return None

    def jump_if_false(self, gv_condition, args_gv):
        return self

    def jump_if_true(self, gv_condition, args_gv):
        return self

    def finish_and_return(self, sigtoken, gv_returnvar):
        pass

    def finish_and_goto(self, outputargs_gv, target):
        pass

    def flexswitch(self, gv_exitswitch, args_gv):
        flexswitch = ReplayFlexSwitch(self)
        return flexswitch, self

    def show_incremental_progress(self):
        pass

class RI386GenOp(AbstractRGenOp):
    from pypy.jit.codegen.i386.codebuf import MachineCodeBlock
    from pypy.jit.codegen.i386.codebuf import InMemoryCodeBuilder

    MC_SIZE = 65536
    
    def __init__(self):
        self.mcs = []   # machine code blocks where no-one is currently writing
        self.keepalive_gc_refs = []
        self.keepalive_float_consts = []
        self.total_code_blocks = 0

    def open_mc(self):
        if self.mcs:
            # XXX think about inserting NOPS for alignment
            return self.mcs.pop()
        else:
            # XXX supposed infinite for now
            self.total_code_blocks += 1
            return self.MachineCodeBlock(self.MC_SIZE)

    def close_mc(self, mc):
        # an open 'mc' is ready for receiving code... but it's also ready
        # for being garbage collected, so be sure to close it if you
        # want the generated code to stay around :-)
        self.mcs.append(mc)

    def check_no_open_mc(self):
        if len(self.mcs) != self.total_code_blocks:
            raise Exception("Open MC!")

    def newbuilder(self, stackdepth):
        return Builder(self, stackdepth)

    def _compute_stack_depth(self, sigtoken):
        arg_tokens, rettoken = sigtoken
        ofs = 0
        for argtoken in arg_tokens:
            ofs += TOKEN_TO_SIZE[argtoken]
        return ofs + WORD

    def newgraph(self, sigtoken, name):
        arg_tokens, res_token = sigtoken
        inputargs_gv = []
        ofs = self._compute_stack_depth(sigtoken)
        builder = self.newbuilder(self._initial_stack_depth(ofs))
        builder._open() # Force builder to have an mc
        entrypoint = builder.mc.tell()
        inputargs_gv = builder._write_prologue(arg_tokens)
        return builder, IntConst(entrypoint), inputargs_gv

    def _initial_stack_depth(self, stackdepth):
        # If a stack depth is a multiple of CALL_ALIGN then the
        # arguments are correctly aligned for a call.  We have to
        # precompute initialstackdepth to guarantee that.  For OS/X the
        # convention is that the stack should be aligned just after all
        # arguments are pushed, i.e. just before the return address is
        # pushed by the CALL instruction.  In other words, after
        # 'numargs' arguments have been pushed the stack is aligned:
        MASK = CALL_ALIGN - 1
        initialstackdepth = ((stackdepth+MASK)&~MASK)
        return initialstackdepth

    def replay(self, label):
        return ReplayBuilder(self), [dummy_var] * len(label.arg_positions)

    @specialize.genconst(1)
    def genconst(self, llvalue):
        T = lltype.typeOf(llvalue)
        if T is llmemory.Address:
            return AddrConst(llvalue)
        elif T is lltype.Signed:
            return IntConst(llvalue)
        elif T is lltype.Unsigned:
            return IntConst(intmask(llvalue))
        elif T is lltype.Char or T is lltype.UniChar:
            # XXX char constant support???
            return IntConst(lltype.cast_primitive(lltype.Signed, llvalue))
        elif T is lltype.Bool:
            return BoolConst(llvalue)
        elif T is lltype.Float:
            res = FloatConst(llvalue)
            self.keepalive_float_consts.append(res)
            return res
        elif isinstance(T, lltype.Ptr):
            lladdr = llmemory.cast_ptr_to_adr(llvalue)
            if T.TO._gckind == 'gc':
                self.keepalive_gc_refs.append(lltype.cast_opaque_ptr(llmemory.GCREF, llvalue))
            return AddrConst(lladdr)
        else:
            assert 0, "XXX not implemented"
    
    # attached later constPrebuiltGlobal = global_rgenop.genconst

    @staticmethod
    @specialize.memo()
    def fieldToken(T, name):
        FIELD = getattr(T, name)
        if isinstance(FIELD, lltype.ContainerType):
            fieldsize = 0      # not useful for getsubstruct
        else:
            fieldsize = llmemory.sizeof(FIELD)
        return (llmemory.offsetof(T, name), fieldsize, map_arg(FIELD))

    @staticmethod
    @specialize.memo()
    def allocToken(T):
        return llmemory.sizeof(T)

    @staticmethod
    @specialize.memo()
    def kindToken(T):
        return map_arg(T)

    @staticmethod
    @specialize.memo()
    def varsizeAllocToken(T):
        if isinstance(T, lltype.Array):
            return RI386GenOp.arrayToken(T)
        else:
            # var-sized structs
            arrayfield = T._arrayfld
            ARRAYFIELD = getattr(T, arrayfield)
            arraytoken = RI386GenOp.arrayToken(ARRAYFIELD)
            length_offset, items_offset, item_size, _ = arraytoken
            arrayfield_offset = llmemory.offsetof(T, arrayfield)
            return (arrayfield_offset+length_offset,
                    arrayfield_offset+items_offset,
                    item_size,
                    '?')

    @classmethod
    @specialize.memo()    
    def arrayToken(cls, A):
        return (llmemory.ArrayLengthOffset(A),
                llmemory.ArrayItemsOffset(A),
                llmemory.ItemOffset(A.OF),
                map_arg(A.OF))

    @staticmethod
    @specialize.memo()
    def sigToken(FUNCTYPE):
        return ([map_arg(arg) for arg in FUNCTYPE.ARGS if arg
                 is not lltype.Void], map_arg(FUNCTYPE.RESULT))

    @staticmethod
    def erasedType(T):
        if T is llmemory.Address:
            return llmemory.Address
        if isinstance(T, lltype.Primitive):
            return lltype.Signed
        elif isinstance(T, lltype.Ptr):
            return llmemory.GCREF
        else:
            assert 0, "XXX not implemented"

    @staticmethod
    @specialize.arg(1)
    def genzeroconst(kind):
        return zero_const

    @staticmethod
    @specialize.arg(0)
    def read_frame_var(T, base, info, index):
        v = info[index]
        value = peek_value_at(T, base - v.stackpos * WORD)
        return value

    @staticmethod
    def genconst_from_frame_var(kind, base, info, index):
        v = info[index]
        if isinstance(v, GenConst):
            return v
        if kind == "f":
            return FloatConst(peek_value_at(lltype.Float, base - v.stackpos * WORD))
        else:
            return IntConst(peek_value_at(lltype.Signed, base - v.stackpos * WORD))

    @staticmethod
    @specialize.arg(0)
    def write_frame_place(T, base, place, value):
        poke_value_into(T, base - place.stackpos * WORD, value)

    @staticmethod
    @specialize.arg(0)
    def read_frame_place(T, base, place):
        return peek_value_at(T, base - place.stackpos * WORD)

global_rgenop = RI386GenOp()
RI386GenOp.constPrebuiltGlobal = global_rgenop.genconst
zero_const = AddrConst(llmemory.NULL)
