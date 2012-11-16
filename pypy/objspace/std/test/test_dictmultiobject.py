import py
import sys
from pypy.interpreter.error import OperationError
from pypy.objspace.std.dictmultiobject import \
     W_DictMultiObject, setitem__DictMulti_ANY_ANY, getitem__DictMulti_ANY, \
     StringDictStrategy, ObjectDictStrategy

class TestW_DictObject:

    def test_empty(self):
        space = self.space
        d = self.space.newdict()
        assert not self.space.is_true(d)
        assert type(d.strategy) is not ObjectDictStrategy

    def test_nonempty(self):
        space = self.space
        wNone = space.w_None
        d = self.space.newdict()
        d.initialize_content([(wNone, wNone)])
        assert space.is_true(d)
        i = space.getitem(d, wNone)
        equal = space.eq(i, wNone)
        assert space.is_true(equal)

    def test_setitem(self):
        space = self.space
        wk1 = space.wrap('key')
        wone = space.wrap(1)
        d = self.space.newdict()
        d.initialize_content([(space.wrap('zero'),space.wrap(0))])
        space.setitem(d,wk1,wone)
        wback = space.getitem(d,wk1)
        assert self.space.eq_w(wback,wone)

    def test_delitem(self):
        space = self.space
        wk1 = space.wrap('key')
        d = self.space.newdict()
        d.initialize_content( [(space.wrap('zero'),space.wrap(0)),
                               (space.wrap('one'),space.wrap(1)),
                               (space.wrap('two'),space.wrap(2))])
        space.delitem(d,space.wrap('one'))
        assert self.space.eq_w(space.getitem(d,space.wrap('zero')),space.wrap(0))
        assert self.space.eq_w(space.getitem(d,space.wrap('two')),space.wrap(2))
        self.space.raises_w(self.space.w_KeyError,
                            space.getitem,d,space.wrap('one'))

    def test_wrap_dict(self):
        assert isinstance(self.space.wrap({}), W_DictMultiObject)


    def test_dict_compare(self):
        w = self.space.wrap
        w0, w1, w2, w3 = map(w, range(4))
        def wd(items):
            d = self.space.newdict()
            d.initialize_content(items)
            return d
        wd1 = wd([(w0, w1), (w2, w3)])
        wd2 = wd([(w2, w3), (w0, w1)])
        assert self.space.eq_w(wd1, wd2)
        wd3 = wd([(w2, w2), (w0, w1)])
        assert not self.space.eq_w(wd1, wd3)
        wd4 = wd([(w3, w3), (w0, w1)])
        assert not self.space.eq_w(wd1, wd4)
        wd5 = wd([(w3, w3)])
        assert not self.space.eq_w(wd1, wd4)

    def test_dict_call(self):
        space = self.space
        w = space.wrap
        def wd(items):
            d = space.newdict()
            d.initialize_content(items)
            return d
        def mydict(w_args=w(()), w_kwds=w({})):
            return space.call(space.w_dict, w_args, w_kwds)
        def deepwrap(lp):
            return [[w(a),w(b)] for a,b in lp]
        d = mydict()
        assert self.space.eq_w(d, w({}))
        args = w(([['a',2],[23,45]],))
        d = mydict(args)
        assert self.space.eq_w(d, wd(deepwrap([['a',2],[23,45]])))
        d = mydict(args, w({'a':33, 'b':44}))
        assert self.space.eq_w(d, wd(deepwrap([['a',33],['b',44],[23,45]])))
        d = mydict(w_kwds=w({'a':33, 'b':44}))
        assert self.space.eq_w(d, wd(deepwrap([['a',33],['b',44]])))
        self.space.raises_w(space.w_TypeError, mydict, w((23,)))
        self.space.raises_w(space.w_ValueError, mydict, w(([[1,2,3]],)))

    def test_dict_pop(self):
        space = self.space
        w = space.wrap
        def mydict(w_args=w(()), w_kwds=w({})):
            return space.call(space.w_dict, w_args, w_kwds)
        d = mydict(w_kwds=w({"1":2, "3":4}))
        dd = mydict(w_kwds=w({"1":2, "3":4})) # means d.copy()
        pop = space.getattr(dd, w("pop"))
        result = space.call_function(pop, w("1"))
        assert self.space.eq_w(result, w(2))
        assert self.space.eq_w(space.len(dd), w(1))

        dd = mydict(w_kwds=w({"1":2, "3":4})) # means d.copy()
        pop = space.getattr(dd, w("pop"))
        result = space.call_function(pop, w("1"), w(44))
        assert self.space.eq_w(result, w(2))
        assert self.space.eq_w(space.len(dd), w(1))
        result = space.call_function(pop, w("1"), w(44))
        assert self.space.eq_w(result, w(44))
        assert self.space.eq_w(space.len(dd), w(1))

        self.space.raises_w(space.w_KeyError, space.call_function, pop, w(33))

    def test_get(self):
        space = self.space
        w = space.wrap
        def mydict(w_args=w(()), w_kwds=w({})):
            return space.call(space.w_dict, w_args, w_kwds)
        d = mydict(w_kwds=w({"1":2, "3":4}))
        get = space.getattr(d, w("get"))
        assert self.space.eq_w(space.call_function(get, w("1")), w(2))
        assert self.space.eq_w(space.call_function(get, w("1"), w(44)), w(2))
        assert self.space.eq_w(space.call_function(get, w("33")), w(None))
        assert self.space.eq_w(space.call_function(get, w("33"), w(44)), w(44))

    def test_fromkeys_fastpath(self):
        space = self.space
        w = space.wrap
        wb = space.wrapbytes

        w_l = self.space.newlist([wb("a"),wb("b")])
        w_l.getitems = None
        w_d = space.call_method(space.w_dict, "fromkeys", w_l)

        assert space.eq_w(w_d.getitem_str("a"), space.w_None)
        assert space.eq_w(w_d.getitem_str("b"), space.w_None)

    def test_listview_str_dict(self):
        w = self.space.wrap
        wb = self.space.wrapbytes
        w_d = self.space.newdict()
        w_d.initialize_content([(wb("a"), w(1)), (wb("b"), w(2))])
        assert self.space.listview_str(w_d) == ["a", "b"]

    def test_listview_unicode_dict(self):
        w = self.space.wrap
        w_d = self.space.newdict()
        w_d.initialize_content([(w(u"a"), w(1)), (w(u"b"), w(2))])
        assert self.space.listview_unicode(w_d) == [u"a", u"b"]

    def test_listview_int_dict(self):
        py.test.py3k_skip("IntDictStrategy not supported yet")
        w = self.space.wrap
        w_d = self.space.newdict()
        w_d.initialize_content([(w(1), w("a")), (w(2), w("b"))])
        assert self.space.listview_int(w_d) == [1, 2]

    def test_keys_on_string_unicode_int_dict(self, monkeypatch):
        w = self.space.wrap
        wb = self.space.wrapbytes
        
        w_d = self.space.newdict()
        w_d.initialize_content([(w(1), wb("a")), (w(2), wb("b"))])
        w_l = self.space.call_method(w_d, "keys")
        assert sorted(self.space.listview_int(w_l)) == [1,2]
        
        # make sure that .keys() calls newlist_str for string dicts
        def not_allowed(*args):
            assert False, 'should not be called'
        monkeypatch.setattr(self.space, 'newlist', not_allowed)
        #
        w_d = self.space.newdict()
        w_d.initialize_content([(w("a"), w(1)), (w("b"), w(6))])
        w_l = self.space.call_method(w_d, "keys")
        assert sorted(self.space.listview_str(w_l)) == ["a", "b"]

        # XXX: it would be nice if the test passed without monkeypatch.undo(),
        # but we need space.newlist_unicode for it
        monkeypatch.undo() 
        w_d = self.space.newdict()
        w_d.initialize_content([(w(u"a"), w(1)), (w(u"b"), w(6))])
        w_l = self.space.call_method(w_d, "keys")
        assert sorted(self.space.listview_unicode(w_l)) == [u"a", u"b"]

class AppTest_DictObject:
    def setup_class(cls):
        cls.w_on_pypy = cls.space.wrap("__pypy__" in sys.builtin_module_names)

    def test_equality(self):
        d = {1: 2}
        f = {1: 2}
        assert d == f
        assert d != {1: 3}

    def test_clear(self):
        d = {1: 2, 3: 4}
        d.clear()
        assert len(d) == 0

    def test_copy(self):
        d = {1: 2, 3: 4}
        dd = d.copy()
        assert d == dd
        assert not d is dd

    def test_get(self):
        d = {1: 2, 3: 4}
        assert d.get(1) == 2
        assert d.get(1, 44) == 2
        assert d.get(33) == None
        assert d.get(33, 44) == 44

    def test_pop(self):
        d = {1: 2, 3: 4}
        dd = d.copy()
        result = dd.pop(1)
        assert result == 2
        assert len(dd) == 1
        dd = d.copy()
        result = dd.pop(1, 44)
        assert result == 2
        assert len(dd) == 1
        result = dd.pop(1, 44)
        assert result == 44
        assert len(dd) == 1
        raises(KeyError, dd.pop, 33)

    def test_items(self):
        d = {1: 2, 3: 4}
        its = list(d.items())
        its.sort()
        assert its == [(1, 2), (3, 4)]

    def test_iteritems(self):
        d = {1: 2, 3: 4}
        dd = d.copy()
        for k, v in d.iteritems():
            assert v == dd[k]
            del dd[k]
        assert not dd

    def test_iterkeys(self):
        d = {1: 2, 3: 4}
        dd = d.copy()
        for k in d.iterkeys():
            del dd[k]
        assert not dd

    def test_itervalues(self):
        d = {1: 2, 3: 4}
        values = []
        for k in d.itervalues():
            values.append(k)
        assert values == list(d.values())

    def test_keys(self):
        d = {1: 2, 3: 4}
        kys = list(d.keys())
        kys.sort()
        assert kys == [1, 3]

    def test_popitem(self):
        d = {1: 2, 3: 4}
        it = d.popitem()
        assert len(d) == 1
        assert it == (1, 2) or it == (3, 4)
        it1 = d.popitem()
        assert len(d) == 0
        assert (it != it1) and (it1 == (1, 2) or it1 == (3, 4))
        raises(KeyError, d.popitem)

    def test_popitem_2(self):
        class A(object):
            pass
        d = A().__dict__
        d['x'] = 5
        it1 = d.popitem()
        assert it1 == ('x', 5)
        raises(KeyError, d.popitem)

    def test_popitem3(self):
        #object
        d = {"a": 1, 2: 2, "c": 3}
        l = []
        while True:
            try:
                l.append(d.popitem())
            except KeyError:
                break;
        assert ("a", 1) in l
        assert (2, 2) in l
        assert ("c", 3) in l

        #string
        d = {"a": 1, "b":2, "c":3}
        l = []
        while True:
            try:
                l.append(d.popitem())
            except KeyError:
                break;
        assert ("a", 1) in l
        assert ("b", 2) in l
        assert ("c", 3) in l

    def test_setdefault(self):
        d = {1: 2, 3: 4}
        dd = d.copy()
        x = dd.setdefault(1, 99)
        assert d == dd
        assert x == 2
        x = dd.setdefault(33, 99)
        d[33] = 99
        assert d == dd
        assert x == 99

    def test_setdefault_fast(self):
        class Key(object):
            calls = 0
            def __hash__(self):
                self.calls += 1
                return object.__hash__(self)

        k = Key()
        d = {}
        d.setdefault(k, [])
        if self.on_pypy:
            assert k.calls == 1

        d.setdefault(k, 1)
        if self.on_pypy:
            assert k.calls == 2

        k = Key()
        d.setdefault(k, 42)
        if self.on_pypy:
            assert k.calls == 1

    def test_update(self):
        d = {1: 2, 3: 4}
        dd = d.copy()
        d.update({})
        assert d == dd
        d.update({3: 5, 6: 7})
        assert d == {1: 2, 3: 5, 6: 7}

    def test_update_iterable(self):
        d = {}
        d.update((('a',1),))
        assert d == {'a': 1}
        d.update([('a',2), ('c',3)])
        assert d == {'a': 2, 'c': 3}

    def test_update_nop(self):
        d = {}
        d.update()
        assert d == {}

    def test_update_kwargs(self):
        d = {}
        d.update(foo='bar', baz=1)
        assert d == {'foo': 'bar', 'baz': 1}

    def test_update_dict_and_kwargs(self):
        d = {}
        d.update({'foo': 'bar'}, baz=1)
        assert d == {'foo': 'bar', 'baz': 1}

    def test_values(self):
        d = {1: 2, 3: 4}
        vals = list(d.values())
        vals.sort()
        assert vals == [2, 4]

    def test_eq(self):
        d1 = {1: 2, 3: 4}
        d2 = {1: 2, 3: 4}
        d3 = {1: 2}
        bool = d1 == d2
        assert bool == True
        bool = d1 == d3
        assert bool == False
        bool = d1 != d2
        assert bool == False
        bool = d1 != d3
        assert bool == True

    def test_lt(self):
        d1 = {1: 2, 3: 4}
        d2 = {1: 2, 3: 4}
        d3 = {1: 2, 3: 5}
        d4 = {1: 2}
        bool = d1 < d2
        assert bool == False
        bool = d1 < d3
        assert bool == True
        bool = d1 < d4
        assert bool == False

    def test_lt2(self):
        assert {'a': 1 } < { 'a': 2 }
        assert not {'a': 1 } > { 'a': 2 }
        assert not {'a': 1, 'b': 0 } > { 'a': 2, 'b': 0 }
        assert {'a': 1, 'b': 0 } < { 'a': 2, 'b': 0 }
        assert {'a': 1, 'b': 0 } < { 'a': 1, 'b': 2 }
        assert not {'a': 1, 'b': 0 } < { 'a': 1, 'b': -2 }
        assert {'a': 1 } < { 'b': 1}
        assert {'a': 1, 'x': 2 } < { 'b': 1, 'x': 2}

    def test_str_repr(self):
        assert '{}' == str({})
        assert '{1: 2}' == str({1: 2})
        assert "{'ba': 'bo'}" == str({'ba': 'bo'})
        # NOTE: the string repr depends on hash values of 1 and 'ba'!!!
        ok_reprs = ["{1: 2, 'ba': 'bo'}", "{'ba': 'bo', 1: 2}"]
        assert str({1: 2, 'ba': 'bo'}) in ok_reprs
        assert '{}' == repr({})
        assert '{1: 2}' == repr({1: 2})
        assert "{'ba': 'bo'}" == repr({'ba': 'bo'})
        assert str({1: 2, 'ba': 'bo'}) in ok_reprs

        # Now test self-containing dict
        d = {}
        d[0] = d
        assert str(d) == '{0: {...}}'

        # Mutating while repr'ing
        class Machiavelli(object):
            def __repr__(self):
                d.clear()
                return "42"
        d = {Machiavelli(): True}
        str(d)
        assert d == {}

    def test_new(self):
        d = dict()
        assert d == {}
        args = [['a', 2], [23, 45]]
        d = dict(args)
        assert d == {'a': 2, 23: 45}
        d = dict(args, a=33, b=44)
        assert d == {'a': 33, 'b': 44, 23: 45}
        d = dict(a=33, b=44)
        assert d == {'a': 33, 'b': 44}
        d = dict({'a': 33, 'b': 44})
        assert d == {'a': 33, 'b': 44}
        raises((TypeError, ValueError), dict, 23)
        raises((TypeError, ValueError), dict, [[1, 2, 3]])

    def test_fromkeys(self):
        assert {}.fromkeys([1, 2], 1) == {1: 1, 2: 1}
        assert {}.fromkeys([1, 2]) == {1: None, 2: None}
        assert {}.fromkeys([]) == {}
        assert {1: 0, 2: 0, 3: 0}.fromkeys([1, '1'], 'j') == (
                          {1: 'j', '1': 'j'})
        class D(dict):
            def __new__(cls):
                return E()
        class E(dict):
            pass
        assert isinstance(D.fromkeys([1, 2]), E)
        assert dict.fromkeys({"a": 2, "b": 3}) == {"a": None, "b": None}
        assert dict.fromkeys({"a": 2, 1: 3}) == {"a": None, 1: None}

    def test_str_uses_repr(self):
        class D(dict):
            def __repr__(self):
                return 'hi'
        assert repr(D()) == 'hi'
        assert str(D()) == 'hi'

    def test_overridden_setitem(self):
        class D(dict):
            def __setitem__(self, key, value):
                dict.__setitem__(self, key, 42)
        d = D([('x', 'foo')], y = 'bar')
        assert d['x'] == 'foo'
        assert d['y'] == 'bar'

        d.setdefault('z', 'baz')
        assert d['z'] == 'baz'

        d['foo'] = 'bar'
        assert d['foo'] == 42

        d.update({'w': 'foobar'})
        assert d['w'] == 'foobar'

        d = d.copy()
        assert d['x'] == 'foo'

        d3 = D.fromkeys(['x', 'y'], 'foo')
        assert d3['x'] == 42
        assert d3['y'] == 42

    def test_overridden_setitem_customkey(self):
        class D(dict):
            def __setitem__(self, key, value):
                dict.__setitem__(self, key, 42)
        class Foo(object):
            pass

        d = D()
        key = Foo()
        d[key] = 'bar'
        assert d[key] == 42

    def test_repr_with_overridden_items(self):
        class D(dict):
            def items(self):
                return []

        d = D([("foo", "foobar")])
        assert repr(d) == "{'foo': 'foobar'}"

    def test_popitem_with_overridden_delitem(self):
        class D(dict):
            def __delitem__(self, key):
                assert False
        d = D()
        d['a'] = 42
        item = d.popitem()
        assert item == ('a', 42)

    def test_dict_update_overridden_getitem(self):
        class D(dict):
            def __getitem__(self, key):
                return 42
        d1 = {}
        d2 = D(a='foo')
        d1.update(d2)
        assert d1['a'] == 'foo'
        # a bit of an obscure case: now (from r78295) we get the same result
        # as CPython does

    def test_index_keyerror_unpacking(self):
        d = {}
        for v1 in ['Q', (1,)]:
            try:
                d[v1]
            except KeyError as e:
                v2 = e.args[0]
                assert v1 == v2
            else:
                assert False, 'Expected KeyError'

    def test_del_keyerror_unpacking(self):
        d = {}
        for v1 in ['Q', (1,)]:
            try:
                del d[v1]
            except KeyError as e:
                v2 = e.args[0]
                assert v1 == v2
            else:
                assert False, 'Expected KeyError'

    def test_pop_keyerror_unpacking(self):
        d = {}
        for v1 in ['Q', (1,)]:
            try:
                d.pop(v1)
            except KeyError as e:
                v2 = e.args[0]
                assert v1 == v2
            else:
                assert False, 'Expected KeyError'

    def test_no_len_on_dict_iter(self):
        iterable = {1: 2, 3: 4}
        raises(TypeError, len, iter(iterable))
        iterable = {"1": 2, "3": 4}
        raises(TypeError, len, iter(iterable))
        iterable = {}
        raises(TypeError, len, iter(iterable))

    def test_missing(self):
        class X(dict):
            def __missing__(self, x):
                assert x == 'hi'
                return 42
        assert X()['hi'] == 42

    def test_missing_more(self):
        def missing(self, x):
            assert x == 'hi'
            return 42
        class SpecialDescr(object):
            def __init__(self, impl):
                self.impl = impl
            def __get__(self, obj, owner):
                return self.impl.__get__(obj, owner)
        class X(dict):
            __missing__ = SpecialDescr(missing)
        assert X()['hi'] == 42

    def test_empty_dict(self):
        d = {}
        raises(KeyError, d.popitem)
        assert list(d.items()) == []
        assert list(d.values()) == []
        assert list(d.keys()) == []

    def test_bytes_keys(self):
        assert isinstance(list({b'a': 1})[0], bytes)


class AppTest_DictMultiObject(AppTest_DictObject):

    def test_emptydict_unhashable(self):
        raises(TypeError, "{}[['x']]")
        raises(TypeError, "del {}[['x']]")

    def test_string_subclass_via_setattr(self):
        class A(object):
            pass
        class S(str):
            def __hash__(self):
                return 123
        a = A()
        s = S("abc")
        setattr(a, s, 42)
        key = next(iter(a.__dict__.keys()))
        assert key == s
        assert key is not s
        assert type(key) is str
        assert getattr(a, s) == 42

    def test_setattr_string_identify(self):
        class StrHolder(object):
            pass
        holder = StrHolder()
        class A(object):
            def __setattr__(self, attr, value):
                holder.seen = attr

        a = A()
        s = "abc"
        setattr(a, s, 123)
        assert holder.seen is s


class AppTestDictViews:
    def test_dictview(self):
        d = {1: 2, 3: 4}
        assert len(d.keys()) == 2
        assert len(d.items()) == 2
        assert len(d.values()) == 2

    def test_constructors_not_callable(self):
        kt = type({}.keys())
        raises(TypeError, kt, {})
        raises(TypeError, kt)
        it = type({}.items())
        raises(TypeError, it, {})
        raises(TypeError, it)
        vt = type({}.values())
        raises(TypeError, vt, {})
        raises(TypeError, vt)

    def test_dict_keys(self):
        d = {1: 10, "a": "ABC"}
        keys = d.keys()
        assert len(keys) == 2
        assert set(keys) == set([1, "a"])
        assert keys == set([1, "a"])
        assert keys == frozenset([1, "a"])
        assert keys != set([1, "a", "b"])
        assert keys != set([1, "b"])
        assert keys != set([1])
        assert keys != 42
        assert 1 in keys
        assert "a" in keys
        assert 10 not in keys
        assert "Z" not in keys
        assert d.keys() == d.keys()
        e = {1: 11, "a": "def"}
        assert d.keys() == e.keys()
        del e["a"]
        assert d.keys() != e.keys()

    def test_dict_items(self):
        d = {1: 10, "a": "ABC"}
        items = d.items()
        assert len(items) == 2
        assert set(items) == set([(1, 10), ("a", "ABC")])
        assert items == set([(1, 10), ("a", "ABC")])
        assert items == frozenset([(1, 10), ("a", "ABC")])
        assert items != set([(1, 10), ("a", "ABC"), "junk"])
        assert items != set([(1, 10), ("a", "def")])
        assert items != set([(1, 10)])
        assert items != 42
        assert (1, 10) in items
        assert ("a", "ABC") in items
        assert (1, 11) not in items
        assert 1 not in items
        assert () not in items
        assert (1,) not in items
        assert (1, 2, 3) not in items
        assert d.items() == d.items()
        e = d.copy()
        assert d.items() == e.items()
        e["a"] = "def"
        assert d.items() != e.items()

    def test_dict_mixed_keys_items(self):
        d = {(1, 1): 11, (2, 2): 22}
        e = {1: 1, 2: 2}
        assert d.keys() == e.items()
        assert d.items() != e.keys()

    def test_dict_values(self):
        d = {1: 10, "a": "ABC"}
        values = d.values()
        assert set(values) == set([10, "ABC"])
        assert len(values) == 2

    def test_dict_repr(self):
        d = {1: 10, "a": "ABC"}
        assert isinstance(repr(d), str)
        r = repr(d.items())
        assert isinstance(r, str)
        assert (r == "dict_items([('a', 'ABC'), (1, 10)])" or
                r == "dict_items([(1, 10), ('a', 'ABC')])")
        r = repr(d.keys())
        assert isinstance(r, str)
        assert (r == "dict_keys(['a', 1])" or
                r == "dict_keys([1, 'a'])")
        r = repr(d.values())
        assert isinstance(r, str)
        assert (r == "dict_values(['ABC', 10])" or
                r == "dict_values([10, 'ABC'])")

    def test_keys_set_operations(self):
        d1 = {'a': 1, 'b': 2}
        d2 = {'b': 3, 'c': 2}
        d3 = {'d': 4, 'e': 5}
        assert d1.keys() & d1.keys() == set('ab')
        assert d1.keys() & d2.keys() == set('b')
        assert d1.keys() & d3.keys() == set()
        assert d1.keys() & set(d1.keys()) == set('ab')
        assert d1.keys() & set(d2.keys()) == set('b')
        assert d1.keys() & set(d3.keys()) == set()

        assert d1.keys() | d1.keys() == set('ab')
        assert d1.keys() | d2.keys() == set('abc')
        assert d1.keys() | d3.keys() == set('abde')
        assert d1.keys() | set(d1.keys()) == set('ab')
        assert d1.keys() | set(d2.keys()) == set('abc')
        assert d1.keys() | set(d3.keys()) == set('abde')

        assert d1.keys() ^ d1.keys() == set()
        assert d1.keys() ^ d2.keys() == set('ac')
        assert d1.keys() ^ d3.keys() == set('abde')
        assert d1.keys() ^ set(d1.keys()) == set()
        assert d1.keys() ^ set(d2.keys()) == set('ac')
        assert d1.keys() ^ set(d3.keys()) == set('abde')

        assert d1.keys() - d1.keys() == set()
        assert d1.keys() - d2.keys() == set('a')
        assert d1.keys() - d3.keys() == set('ab')
        assert d1.keys() - set(d1.keys()) == set()
        assert d1.keys() - set(d2.keys()) == set('a')
        assert d1.keys() - set(d3.keys()) == set('ab')

        assert not d1.keys().isdisjoint(d1.keys())
        assert not d1.keys().isdisjoint(d2.keys())
        assert not d1.keys().isdisjoint(list(d2.keys()))
        assert not d1.keys().isdisjoint(set(d2.keys()))
        
        assert d1.keys().isdisjoint(['x', 'y', 'z'])
        assert d1.keys().isdisjoint(set(['x', 'y', 'z']))
        assert d1.keys().isdisjoint(set(['x', 'y']))
        assert d1.keys().isdisjoint(['x', 'y'])
        assert d1.keys().isdisjoint({})
        assert d1.keys().isdisjoint(d3.keys())

        de = {}
        assert de.keys().isdisjoint(set())
        assert de.keys().isdisjoint([])
        assert de.keys().isdisjoint(de.keys())
        assert de.keys().isdisjoint([1])


    def test_items_set_operations(self):
        d1 = {'a': 1, 'b': 2}
        d2 = {'a': 2, 'b': 2}
        d3 = {'d': 4, 'e': 5}
        assert d1.items() & d1.items() == set([('a', 1), ('b', 2)])
        assert d1.items() & d2.items() == set([('b', 2)])
        assert d1.items() & d3.items() == set()
        assert d1.items() & set(d1.items()) == set([('a', 1), ('b', 2)])
        assert d1.items() & set(d2.items()) == set([('b', 2)])
        assert d1.items() & set(d3.items()) == set()

        assert d1.items() | d1.items() == set([('a', 1), ('b', 2)])
        assert (d1.items() | d2.items() ==
                set([('a', 1), ('a', 2), ('b', 2)]))
        assert (d1.items() | d3.items() ==
                set([('a', 1), ('b', 2), ('d', 4), ('e', 5)]))
        assert (d1.items() | set(d1.items()) ==
                set([('a', 1), ('b', 2)]))
        assert (d1.items() | set(d2.items()) ==
                set([('a', 1), ('a', 2), ('b', 2)]))
        assert (d1.items() | set(d3.items()) ==
                set([('a', 1), ('b', 2), ('d', 4), ('e', 5)]))

        assert d1.items() ^ d1.items() == set()
        assert d1.items() ^ d2.items() == set([('a', 1), ('a', 2)])
        assert (d1.items() ^ d3.items() ==
                set([('a', 1), ('b', 2), ('d', 4), ('e', 5)]))

        assert d1.items() - d1.items() == set()
        assert d1.items() - d2.items() == set([('a', 1)])
        assert d1.items() - d3.items() == set([('a', 1), ('b', 2)])

        assert not d1.items().isdisjoint(d1.items())
        assert not d1.items().isdisjoint(d2.items())
        assert not d1.items().isdisjoint(list(d2.items()))
        assert not d1.items().isdisjoint(set(d2.items()))
        assert d1.items().isdisjoint(['x', 'y', 'z'])
        assert d1.items().isdisjoint(set(['x', 'y', 'z']))
        assert d1.items().isdisjoint(set(['x', 'y']))
        assert d1.items().isdisjoint({})
        assert d1.items().isdisjoint(d3.items())

        de = {}
        assert de.items().isdisjoint(set())
        assert de.items().isdisjoint([])
        assert de.items().isdisjoint(de.items())
        assert de.items().isdisjoint([1])

    def test_keys_set_operations_any_type(self):
        """
        d = {1: 'a', 2: 'b', 3: 'c'}
        assert d.keys() & {1} == {1}
        assert d.keys() & {1: 'foo'} == {1}
        assert d.keys() & [1, 2] == {1, 2}
        #
        assert {1} & d.keys() == {1}
        assert {1: 'foo'} & d.keys() == {1}
        assert [1, 2] & d.keys() == {1, 2}
        #
        assert d.keys() - {1} == {2, 3}
        assert {1, 4} - d.keys() == {4}
        #
        assert d.keys() == {1, 2, 3}
        assert {1, 2, 3} == d.keys()
        assert d.keys() == frozenset({1, 2, 3})
        assert frozenset({1, 2, 3}) == d.keys()
        assert not d.keys() != {1, 2, 3}
        assert not {1, 2, 3} != d.keys()
        assert not d.keys() != frozenset({1, 2, 3})
        assert not frozenset({1, 2, 3}) != d.keys()
        """

    def test_items_set_operations_any_type(self):
        """
        d = {1: 'a', 2: 'b', 3: 'c'}
        assert d.items() & {(1, 'a')} == {(1, 'a')}
        assert d.items() & {(1, 'a'): 'foo'} == {(1, 'a')}
        assert d.items() & [(1, 'a'), (2, 'b')] == {(1, 'a'), (2, 'b')}
        #
        assert {(1, 'a')} & d.items() == {(1, 'a')}
        assert {(1, 'a'): 'foo'} & d.items() == {(1, 'a')}
        assert [(1, 'a'), (2, 'b')] & d.items() == {(1, 'a'), (2, 'b')}
        #
        assert d.items() - {(1, 'a')} == {(2, 'b'), (3, 'c')}
        assert {(1, 'a'), 4} - d.items() == {4}
        #
        assert d.items() == {(1, 'a'), (2, 'b'), (3, 'c')}
        assert {(1, 'a'), (2, 'b'), (3, 'c')} == d.items()
        assert d.items() == frozenset({(1, 'a'), (2, 'b'), (3, 'c')})
        assert frozenset({(1, 'a'), (2, 'b'), (3, 'c')}) == d.items()
        assert not d.items() != {(1, 'a'), (2, 'b'), (3, 'c')}
        assert not {(1, 'a'), (2, 'b'), (3, 'c')} != d.items()
        assert not d.items() != frozenset({(1, 'a'), (2, 'b'), (3, 'c')})
        assert not frozenset({(1, 'a'), (2, 'b'), (3, 'c')}) != d.items()
        """

    def test_dictviewset_unshasable_values(self):
        class C:
            def __eq__(self, other):
                return True
        d = {1: C()}
        assert d.items() <= d.items()

    def test_compare_keys_and_items(self):
        d1 = {1: 2}
        d2 = {(1, 2): 'foo'}
        assert d1.items() == d2.keys()

    def test_keys_items_contained(self):
        def helper(fn):
            empty = fn(dict())
            empty2 = fn(dict())
            smaller = fn({1:1, 2:2})
            larger = fn({1:1, 2:2, 3:3})
            larger2 = fn({1:1, 2:2, 3:3})
            larger3 = fn({4:1, 2:2, 3:3})

            assert smaller <  larger
            assert smaller <= larger
            assert larger >  smaller
            assert larger >= smaller

            assert not smaller >= larger
            assert not smaller >  larger
            assert not larger  <= smaller
            assert not larger  <  smaller

            assert not smaller <  larger3
            assert not smaller <= larger3
            assert not larger3 >  smaller
            assert not larger3 >= smaller

            # Inequality strictness
            assert larger2 >= larger
            assert larger2 <= larger
            assert not larger2 > larger
            assert not larger2 < larger

            assert larger == larger2
            assert smaller != larger

            # There is an optimization on the zero-element case.
            assert empty == empty2
            assert not empty != empty2
            assert not empty == smaller
            assert empty != smaller

            # With the same size, an elementwise compare happens
            assert larger != larger3
            assert not larger == larger3

        helper(lambda x: x.keys())
        helper(lambda x: x.items())

class AppTestStrategies(object):
    def setup_class(cls):
        if cls.runappdirect:
            py.test.skip("__repr__ doesn't work on appdirect")

    def w_get_strategy(self, obj):
        import __pypy__
        r = __pypy__.internal_repr(obj)
        return r[r.find("(") + 1: r.find(")")]

    def test_empty_to_string(self):
        py3k_skip("StringDictStrategy not supported yet")
        d = {}
        assert "EmptyDictStrategy" in self.get_strategy(d)
        d["a"] = 1
        assert "StringDictStrategy" in self.get_strategy(d)

        class O(object):
            pass
        o = O()
        d = o.__dict__ = {}
        assert "EmptyDictStrategy" in self.get_strategy(d)
        o.a = 1
        assert "StringDictStrategy" in self.get_strategy(d)

    def test_empty_to_unicode(self):
        d = {}
        assert "EmptyDictStrategy" in self.get_strategy(d)
        d["a"] = 1
        assert "UnicodeDictStrategy" in self.get_strategy(d)
        assert d["a"] == 1
        #assert d[b"a"] == 1 # this works in py2, but not in py3
        assert list(d.keys()) == ["a"]
        assert type(list(d.keys())[0]) is str

    def test_empty_to_int(self):
        skip('IntDictStrategy is disabled for now, re-enable it!')
        import sys
        d = {}
        d[1] = "hi"
        assert "IntDictStrategy" in self.get_strategy(d)

    def test_iter_dict_length_change(self):
        d = {1: 2, 3: 4, 5: 6}
        it = d.iteritems()
        d[7] = 8
        # 'd' is now length 4
        raises(RuntimeError, it.__next__)

    def test_iter_dict_strategy_only_change_1(self):
        d = {1: 2, 3: 4, 5: 6}
        it = d.iteritems()
        class Foo(object):
            def __eq__(self, other):
                return False
            def __hash__(self):
                return 0
        assert d.get(Foo()) is None    # this changes the strategy of 'd'
        lst = list(it)  # but iterating still works
        assert sorted(lst) == [(1, 2), (3, 4), (5, 6)]

    def test_iter_dict_strategy_only_change_2(self):
        d = {1: 2, 3: 4, 5: 6}
        it = d.iteritems()
        d['foo'] = 'bar'
        del d[1]
        # on default the strategy changes and thus we get the RuntimeError
        # (commented below). On py3k, we Int and String strategies don't work
        # yet, and thus we get the "correct" behavior
        items = list(it)
        assert set(items) == set([(3, 4), (5, 6), ('foo', 'bar')])
        # 'd' is still length 3, but its strategy changed.  we are
        # getting a RuntimeError because iterating over the old storage
        # gives us (1, 2), but 1 is not in the dict any longer.
        #raises(RuntimeError, list, it)


class FakeWrapper(object):
    hash_count = 0
    def unwrap(self, space):
        self.unwrapped = True
        return str(self)

    def __hash__(self):
        self.hash_count += 1
        return str.__hash__(self)

class FakeString(FakeWrapper, str):
    pass

class FakeUnicode(FakeWrapper, unicode):
    pass

# the minimal 'space' needed to use a W_DictMultiObject
class FakeSpace:
    hash_count = 0
    def hash_w(self, obj):
        self.hash_count += 1
        return hash(obj)
    def unwrap(self, x):
        return x
    def is_true(self, x):
        return x
    def is_(self, x, y):
        return x is y
    is_w = is_
    def eq(self, x, y):
        return x == y
    eq_w = eq
    def newlist(self, l):
        return l
    def newlist_str(self, l):
        return l
    DictObjectCls = W_DictMultiObject
    def type(self, w_obj):
        if isinstance(w_obj, FakeString):
            return str
        return type(w_obj)
    w_str = str
    def str_w(self, string):
        assert isinstance(string, str)
        return string

    def int_w(self, integer):
        assert isinstance(integer, int)
        return integer

    def wrap(self, obj):
        return obj

    def isinstance(self, obj, klass):
        return isinstance(obj, klass)

    def newtuple(self, l):
        return tuple(l)

    def newdict(self, module=False, instance=False):
        return W_DictMultiObject.allocate_and_init_instance(
                self, module=module, instance=instance)

    def view_as_kwargs(self, w_d):
        return w_d.view_as_kwargs() # assume it's a multidict

    def finditem_str(self, w_dict, s):
        return w_dict.getitem_str(s) # assume it's a multidict

    def setitem_str(self, w_dict, s, w_value):
        return w_dict.setitem_str(s, w_value) # assume it's a multidict

    def delitem(self, w_dict, w_s):
        return w_dict.delitem(w_s) # assume it's a multidict

    def allocate_instance(self, cls, type):
        return object.__new__(cls)

    def fromcache(self, cls):
        return cls(self)

    w_StopIteration = StopIteration
    w_None = None
    w_NoneType = type(None, None)
    w_int = int
    w_bool = bool
    w_float = float
    StringObjectCls = FakeString
    UnicodeObjectCls = FakeUnicode
    w_dict = W_DictMultiObject
    w_text = str
    iter = iter
    fixedview = list
    listview  = list

class Config:
    class objspace:
        class std:
            withsmalldicts = False
            withcelldict = False
            withmethodcache = False
            withidentitydict = False

FakeSpace.config = Config()


class TestDictImplementation:
    def setup_method(self,method):
        self.space = FakeSpace()

    def test_stressdict(self):
        from random import randint
        d = self.space.newdict()
        N = 10000
        pydict = {}
        for i in range(N):
            x = randint(-N, N)
            setitem__DictMulti_ANY_ANY(self.space, d, x, i)
            pydict[x] = i
        for key, value in pydict.iteritems():
            assert value == getitem__DictMulti_ANY(self.space, d, key)

class BaseTestRDictImplementation:

    def setup_method(self,method):
        self.fakespace = FakeSpace()
        self.string = self.fakespace.wrap("fish")
        self.string2 = self.fakespace.wrap("fish2")
        self.impl = self.get_impl()

    def get_impl(self):
        strategy = self.StrategyClass(self.fakespace)
        storage = strategy.get_empty_storage()
        w_dict = self.fakespace.allocate_instance(W_DictMultiObject, None)
        W_DictMultiObject.__init__(w_dict, self.fakespace, strategy, storage)
        return w_dict

    def fill_impl(self):
        self.impl.setitem(self.string, 1000)
        self.impl.setitem(self.string2, 2000)

    def check_not_devolved(self):
        #XXX check if strategy changed!?
        assert type(self.impl.strategy) is self.StrategyClass
        #assert self.impl.r_dict_content is None

    def test_popitem(self):
        self.fill_impl()
        assert self.impl.length() == 2
        a, b = self.impl.popitem()
        assert self.impl.length() == 1
        if a == self.string:
            assert b == 1000
            assert self.impl.getitem(self.string2) == 2000
        else:
            assert a == self.string2
            assert b == 2000
            assert self.impl.getitem_str(self.string) == 1000
        self.check_not_devolved()

    def test_setitem(self):
        self.impl.setitem(self.string, 1000)
        assert self.impl.length() == 1
        assert self.impl.getitem(self.string) == 1000
        assert self.impl.getitem_str(self.string) == 1000
        self.check_not_devolved()

    def test_setitem_str(self):
        self.impl.setitem_str(self.fakespace.str_w(self.string), 1000)
        assert self.impl.length() == 1
        assert self.impl.getitem(self.string) == 1000
        assert self.impl.getitem_str(self.string) == 1000
        self.check_not_devolved()

    def test_delitem(self):
        self.fill_impl()
        assert self.impl.length() == 2
        self.impl.delitem(self.string2)
        assert self.impl.length() == 1
        self.impl.delitem(self.string)
        assert self.impl.length() == 0
        self.check_not_devolved()

    def test_clear(self):
        self.fill_impl()
        assert self.impl.length() == 2
        self.impl.clear()
        assert self.impl.length() == 0
        self.check_not_devolved()


    def test_keys(self):
        self.fill_impl()
        keys = self.impl.w_keys() # wrapped lists = lists in the fake space
        keys.sort()
        assert keys == [self.string, self.string2]
        self.check_not_devolved()

    def test_values(self):
        self.fill_impl()
        values = self.impl.values()
        values.sort()
        assert values == [1000, 2000]
        self.check_not_devolved()

    def test_items(self):
        self.fill_impl()
        items = self.impl.items()
        items.sort()
        assert items == zip([self.string, self.string2], [1000, 2000])
        self.check_not_devolved()

    def test_iter(self):
        self.fill_impl()
        iteratorimplementation = self.impl.iteritems()
        items = []
        while 1:
            item = iteratorimplementation.next_item()
            if item == (None, None):
                break
            items.append(item)
        items.sort()
        assert items == zip([self.string, self.string2], [1000, 2000])
        self.check_not_devolved()

    def test_devolve(self):
        impl = self.impl
        for x in xrange(100):
            impl.setitem(self.fakespace.str_w(str(x)), x)
            impl.setitem(x, x)
        assert type(impl.strategy) is ObjectDictStrategy

    def test_setdefault_fast(self):
        on_pypy = "__pypy__" in sys.builtin_module_names
        impl = self.impl
        key = FakeString(self.string)
        x = impl.setdefault(key, 1)
        assert x == 1
        if on_pypy:
            assert key.hash_count == 1
        x = impl.setdefault(key, 2)
        assert x == 1
        if on_pypy:
            assert key.hash_count == 2

    def test_fallback_evil_key(self):
        class F(object):
            def __hash__(self):
                return hash("s")
            def __eq__(self, other):
                return other == "s"

        d = self.get_impl()
        d.setitem("s", 12)
        assert d.getitem("s") == 12
        assert d.getitem(F()) == d.getitem("s")

        d = self.get_impl()
        x = d.setdefault("s", 12)
        assert x == 12
        x = d.setdefault(F(), 12)
        assert x == 12

        d = self.get_impl()
        x = d.setdefault(F(), 12)
        assert x == 12

        d = self.get_impl()
        d.setitem("s", 12)
        d.delitem(F())

        assert "s" not in d.w_keys()
        assert F() not in d.w_keys()

class TestStrDictImplementation(BaseTestRDictImplementation):
    StrategyClass = StringDictStrategy
    #ImplementionClass = StrDictImplementation

    def test_str_shortcut(self):
        self.fill_impl()
        s = FakeString(self.string)
        assert self.impl.getitem(s) == 1000
        assert s.unwrapped

    def test_view_as_kwargs(self):
        self.fill_impl()
        assert self.fakespace.view_as_kwargs(self.impl) == (["fish", "fish2"], [1000, 2000])

## class TestMeasuringDictImplementation(BaseTestRDictImplementation):
##     ImplementionClass = MeasuringDictImplementation
##     DevolvedClass = MeasuringDictImplementation

class BaseTestDevolvedDictImplementation(BaseTestRDictImplementation):
    def fill_impl(self):
        BaseTestRDictImplementation.fill_impl(self)
        self.impl.strategy.switch_to_object_strategy(self.impl)

    def check_not_devolved(self):
        pass

class TestDevolvedStrDictImplementation(BaseTestDevolvedDictImplementation):
    StrategyClass = StringDictStrategy


def test_module_uses_strdict():
    fakespace = FakeSpace()
    d = fakespace.newdict(module=True)
    assert type(d.strategy) is StringDictStrategy

