
from rpython.rtyper.lltypesystem import lltype, rstr, llmemory

from rpython.jit.codewriter.effectinfo import EffectInfo
from rpython.jit.metainterp.resoperation import rop
from rpython.jit.metainterp.history import ConstInt, INT
from rpython.jit.codewriter import heaptracker
from rpython.jit.resume import rescode

class ResumeFrame(object):
    def __init__(self, jitcode):
        self.registers = [rescode.CLEAR_POSITION] * jitcode.num_regs()
        self.jitcode = jitcode
        self.pc = -1

class BaseVirtual(object):
    def populate_fields(self, reader):
        pass

class BaseVirtualStruct(BaseVirtual):
    def populate_fields(self, val, reader):
        fields = self.fields
        for fielddescr, encoded_field_pos in fields.iteritems():
            reader.setfield_gc(val, encoded_field_pos, fielddescr)

    def populate_fields_boxes(self, box, reader):
        for fielddescr, encoded_field_pos in self.fields.iteritems():
            reader.setfield_gc(box, encoded_field_pos, fielddescr)

class VirtualStruct(BaseVirtualStruct):
    def __init__(self, pos, descr):
        self.pos = pos
        self.fields = {}
        self.descr = descr

    def allocate_box(self, metainterp):
        return metainterp.execute_and_record(rop.NEW, self.descr)

    def allocate_direct(self, reader, cpu):
        return cpu.bh_new(self.descr)
    
class VirtualWithVtable(BaseVirtualStruct):
    def __init__(self, pos, const_class):
        self.pos = pos
        self.const_class = const_class
        self.fields = {}

    def allocate_box(self, metainterp):
        return metainterp.execute_and_record(rop.NEW_WITH_VTABLE, None,
                                             ConstInt(self.const_class))

    def allocate_direct(self, reader, cpu):
        descr = heaptracker.vtable2descr(cpu, self.const_class)
        return cpu.bh_new_with_vtable(self.const_class, descr)

class VirtualStr(BaseVirtual):
    def __init__(self, pos, lgt, mode):
        self.pos = pos
        self.lgt = lgt
        self.mode = mode
        self.chars = [-1] * lgt

    def populate_fields_boxes(self, box, reader):
        for i in range(len(self.chars)):
            ch = self.chars[i]
            if ch != -1:
                vbox = reader.get_box_value(-1, -1, ch, INT)
                reader.strsetitem(box, ConstInt(i), vbox, self.mode)

    def populate_fields(self, val, reader):
        for i in range(len(self.chars)):
            ch = self.chars[i]
            if ch != -1:
                itemval = reader.getint(ch)
                reader.strsetitem(val, i, itemval, self.mode)

    def allocate_box(self, metainterp):
        if self.mode == 's':
            resop = rop.NEWSTR
        else:
            resop = rop.NEWUNICODE
        return metainterp.execute_and_record(resop, [ConstInt(self.lgt)])

    def allocate_direct(self, reader, cpu):
        if self.mode == 's':
            return cpu.bh_newstr(self.lgt)
        return cpu.bh_newunicode(self.lgt)

class VirtualConcat(BaseVirtual):
    def __init__(self, pos, left, right, mode):
        self.pos = pos
        self.left = left
        self.right = right
        self.mode = mode

    def populate_fields_boxes(self, box, reader):
        pass

    def populate_fields(self, val, reader):
        pass

    def allocate_direct(self, reader, cpu):
        leftval = reader.getref(self.left)
        rightval = reader.getref(self.right)
        cic = reader.staticdata.callinfocollection
        if self.mode == 'u':
            funcptr = cic.funcptr_for_oopspec(EffectInfo.OS_UNI_CONCAT)
            str1 = lltype.cast_opaque_ptr(lltype.Ptr(rstr.UNICODE), leftval)
            str2 = lltype.cast_opaque_ptr(lltype.Ptr(rstr.UNICODE), rightval)
            result = funcptr(str1, str2)
            return lltype.cast_opaque_ptr(llmemory.GCREF, result)
        else:
            xxx

class AbstractResumeReader(object):
    """ A resume reader that can follow resume until given point. Consult
    the concrete classes for details
    """
    
    def __init__(self, staticdata):
        self.framestack = []
        self.staticdata = staticdata
        self.virtuals = []

    def rebuild(self, faildescr):
        self._rebuild_until(faildescr.rd_resume_bytecode,
                            faildescr.rd_bytecode_position)
        return self.finish()

    def finish(self):
        pass

    def enter_frame(self, pc, jitcode):
        if self.framestack:
            assert pc != -1
            self.framestack[-1].pc = pc
        self.framestack.append(ResumeFrame(jitcode))

    def decode(self, pos):
        return pos & 0x3, pos >> rescode.TAGOFFSET

    def resume_put(self, encoded_pos, frame_no, frontend_position):
        self.framestack[frame_no].registers[frontend_position] = encoded_pos

    def resume_new(self, v_pos, descr):
        v = VirtualStruct(v_pos, descr)
        self._add_to_virtuals(v, v_pos)

    def resume_newstr(self, v_pos, lgt):
        v = VirtualStr(v_pos, lgt, 's')
        self._add_to_virtuals(v, v_pos)

    def resume_newunicode(self, v_pos, lgt):
        v = VirtualStr(v_pos, lgt, 'u')
        self._add_to_virtuals(v, v_pos)

    def resume_concatstr(self, v_pos, leftpos, rightpos):
        v = VirtualConcat(v_pos, leftpos, rightpos, 's')
        self._add_to_virtuals(v, v_pos)

    def resume_concatunicode(self, v_pos, leftpos, rightpos):
        v = VirtualConcat(v_pos, leftpos, rightpos, 'u')
        self._add_to_virtuals(v, v_pos)

    def resume_strsetitem(self, v_pos, index, sourcepos):
        v = self.virtuals[v_pos]
        assert isinstance(v, VirtualStr)
        v.chars[index] = sourcepos

    def resume_new_with_vtable(self, v_pos, c_const_class):
        const_class = c_const_class.getint()
        v = VirtualWithVtable(v_pos, const_class)
        self._add_to_virtuals(v, v_pos)

    def _add_to_virtuals(self, v, v_pos):
        if v_pos >= len(self.virtuals):
            self.virtuals += [None] * (len(self.virtuals) - v_pos + 1)
        self.virtuals[v_pos] = v
        
    def resume_setfield_gc(self, pos, fieldpos, descr):
        # XXX optimize fields
        tag, index = self.decode(pos)
        assert tag == rescode.TAGVIRTUAL # for now
        self.virtuals[index].fields[descr] = fieldpos

    def resume_clear(self, frame_no, frontend_position):
        self.framestack[frame_no].registers[frontend_position] = rescode.CLEAR_POSITION

    def resume_set_pc(self, pc):
        self.framestack[-1].pc = pc

    def leave_frame(self):
        self.framestack.pop()

    def _rebuild_until(self, rb, position):
        self.consts = rb.consts
        self.interpret_until(rb, position)

    def read(self, pos):
        return ord(self.bytecode.opcodes[pos])

    def read_short(self, pos):
        return self.read(pos) + (self.read(pos + 1) << 8)

    def interpret_until(self, bytecode, until, pos=0):
        self.bytecode = bytecode
        while pos < until:
            op = ord(bytecode.opcodes[pos])
            if op == rescode.UNUSED:
                raise Exception("malformed bytecode")
            elif op == rescode.ENTER_FRAME:
                pc = self.read_short(pos + 1) - 1
                jitcode = self.staticdata.alljitcodes[self.read_short(pos + 3)]
                self.enter_frame(pc, jitcode)
                pos += 5
            elif op == rescode.LEAVE_FRAME:
                self.leave_frame()
                pos += 1
            elif op == rescode.RESUME_PUT:
                encoded = self.read_short(pos + 1)
                frame_pos = self.read(pos + 3)
                pos_in_frame = self.read(pos + 4)
                self.resume_put(encoded, frame_pos, pos_in_frame)
                pos += 5
            elif op == rescode.RESUME_NEW:
                v_pos = self.read_short(pos + 1)
                descr = self.staticdata.opcode_descrs[self.read_short(pos + 3)]
                self.resume_new(v_pos, descr)
                pos += 5
            elif op == rescode.RESUME_NEW_WITH_VTABLE:
                v_pos = self.read_short(pos + 1)
                const_class = self.consts[self.read_short(pos + 3)]
                self.resume_new_with_vtable(v_pos, const_class)
                pos += 5
            elif op == rescode.RESUME_SETFIELD_GC:
                structpos = self.read_short(pos + 1)
                fieldpos = self.read_short(pos + 3)
                descr = self.staticdata.opcode_descrs[self.read_short(pos + 5)]
                self.resume_setfield_gc(structpos, fieldpos, descr)
                pos += 7
            elif op == rescode.RESUME_CLEAR:
                frame_pos = self.read(pos + 1)
                pos_in_frame = self.read(pos + 2)
                self.resume_clear(frame_pos, pos_in_frame)
                pos += 3
            elif op == rescode.RESUME_SET_PC:
                pc = self.read_short(pos + 1)
                self.resume_set_pc(pc)
                pos += 3
            elif op == rescode.RESUME_NEWSTR:
                v_pos = self.read_short(pos + 1)
                lgt = self.read(pos + 3)
                self.resume_newstr(v_pos, lgt)
                pos += 4
            elif op == rescode.RESUME_NEWUNICODE:
                v_pos = self.read_short(pos + 1)
                lgt = self.read(pos + 3)
                self.resume_newunicode(v_pos, lgt)
                pos += 4
            elif op == rescode.RESUME_CONCATSTR:
                xxx
            elif op == rescode.RESUME_CONCATUNICODE:
                v_pos = self.read_short(pos + 1)
                left = self.read_short(pos + 3)
                right = self.read_short(pos + 5)
                self.resume_concatunicode(v_pos, left, right)
                pos += 7
            elif op == rescode.RESUME_STRSETITEM:
                v_pos = self.read_short(pos + 1)
                index = self.read(pos + 3)
                source = self.read(pos + 4)
                self.resume_strsetitem(v_pos, index, source)
                pos += 6
            else:
                xxx
        self.bytecode = None

    def read_int(self, jitframe_pos):
        return self.metainterp.cpu.get_int_value(self.deadframe, jitframe_pos)

class Dumper(AbstractResumeReader):
    def __init__(self, staticdata):
        AbstractResumeReader.__init__(self, staticdata)
        self.l = []

    def enter_frame(self, pc, jitcode):
        self.l.append("enter_frame %d %s" % (pc, jitcode.name))

    def resume_put(self, encoded, frame_pos, pos_in_frame):
        tag, index = self.decode(encoded)
        self.l.append("resume_put (%d, %d) %d %d" % (tag, index, frame_pos,
                                                     pos_in_frame))

    def resume_new(self, v_pos, descr):
        self.l.append("%d = resume_new %d" % (v_pos, descr.global_descr_index))

    def resume_clear(self, frame_pos, pos_in_frame):
        self.l.append("resume_clear %d %d" % (frame_pos, pos_in_frame))

    def resume_newstr(self, v_pos, lgt):
        xxx

    def resume_newunicode(self, v_pos, lgt):
        xxx

    def resume_concatstr(self, v_pos, leftpos, rightpos):
        xxx

    def resume_concatunicode(self, v_pos, leftpos, rightpos):
        xxx

    def resume_new_with_vtable(self, v_pos, c_const_class):
        self.l.append("%d = resume_new_with_vtable %d" % (v_pos,
                                                c_const_class.getint()))

    def leave_frame(self):
        self.l.append("leave_frame")

    def resume_setfield_gc(self, structpos, fieldpos, descr):
        stag, sindex = self.decode(structpos)
        ftag, findex = self.decode(fieldpos)
        self.l.append("resume_setfield_gc (%d, %d) (%d, %d) %d" % (
            stag, sindex, ftag, findex, descr.global_descr_index))

    def resume_set_pc(self, pc):
        self.l.append("set_resume_pc %d" % pc)

    def finish(self):
        return "\n".join(self.l)
