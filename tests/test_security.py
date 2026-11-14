import pytest
from markupsafe import escape

from jinja2 import Environment
from jinja2 import StrictUndefined
from jinja2 import Undefined
from jinja2.exceptions import SecurityError
from jinja2.exceptions import TemplateRuntimeError
from jinja2.exceptions import TemplateSyntaxError
from jinja2.nodes import EvalContext
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.sandbox import SandboxedEnvironment
from jinja2.sandbox import unsafe


class PrivateStuff:
    def bar(self):
        return 23

    @unsafe
    def foo(self):
        return 42

    def __repr__(self):
        return "PrivateStuff"


class PublicStuff:
    def bar(self):
        return 23

    def _foo(self):
        return 42

    def __repr__(self):
        return "PublicStuff"


class TestSandbox:
    def test_unsafe(self, env):
        env = SandboxedEnvironment()
        pytest.raises(
            SecurityError, env.from_string("{{ foo.foo() }}").render, foo=PrivateStuff()
        )
        assert env.from_string("{{ foo.bar() }}").render(foo=PrivateStuff()) == "23"

        pytest.raises(
            SecurityError, env.from_string("{{ foo._foo() }}").render, foo=PublicStuff()
        )
        assert env.from_string("{{ foo.bar() }}").render(foo=PublicStuff()) == "23"
        assert env.from_string("{{ foo.__class__ }}").render(foo=42) == ""
        assert env.from_string("{{ foo.func_code }}").render(foo=lambda: None) == ""
        # security error comes from __class__ already.
        pytest.raises(
            SecurityError,
            env.from_string("{{ foo.__class__.__subclasses__() }}").render,
            foo=42,
        )

    def test_immutable_environment(self, env):
        env = ImmutableSandboxedEnvironment()
        pytest.raises(SecurityError, env.from_string("{{ [].append(23) }}").render)
        pytest.raises(SecurityError, env.from_string("{{ [].clear() }}").render)
        pytest.raises(SecurityError, env.from_string("{{ [1].pop() }}").render)
        pytest.raises(SecurityError, env.from_string("{{ {1:2}.clear() }}").render)

    def test_restricted(self, env):
        env = SandboxedEnvironment()
        pytest.raises(
            TemplateSyntaxError,
            env.from_string,
            "{% for item.attribute in seq %}...{% endfor %}",
        )
        pytest.raises(
            TemplateSyntaxError,
            env.from_string,
            "{% for foo, bar.baz in seq %}...{% endfor %}",
        )

    def test_template_data(self, env):
        env = Environment(autoescape=True)
        t = env.from_string(
            "{% macro say_hello(name) %}"
            "<p>Hello {{ name }}!</p>{% endmacro %}"
            '{{ say_hello("<blink>foo</blink>") }}'
        )
        escaped_out = "<p>Hello &lt;blink&gt;foo&lt;/blink&gt;!</p>"
        assert t.render() == escaped_out
        assert str(t.module) == escaped_out
        assert escape(t.module) == escaped_out
        assert t.module.say_hello("<blink>foo</blink>") == escaped_out
        assert (
            escape(t.module.say_hello(EvalContext(env), "<blink>foo</blink>"))
            == escaped_out
        )
        assert escape(t.module.say_hello("<blink>foo</blink>")) == escaped_out

    def test_attr_filter(self, env):
        env = SandboxedEnvironment()
        tmpl = env.from_string('{{ cls|attr("__subclasses__")() }}')
        pytest.raises(SecurityError, tmpl.render, cls=int)

    def test_binary_operator_intercepting(self, env):
        def disable_op(left, right):
            raise TemplateRuntimeError("that operator so does not work")

        for expr, ctx, rv in ("1 + 2", {}, "3"), ("a + 2", {"a": 2}, "4"):
            env = SandboxedEnvironment()
            env.binop_table["+"] = disable_op
            t = env.from_string(f"{{{{ {expr} }}}}")
            assert t.render(ctx) == rv
            env.intercepted_binops = frozenset(["+"])
            t = env.from_string(f"{{{{ {expr} }}}}")
            with pytest.raises(TemplateRuntimeError):
                t.render(ctx)

    def test_unary_operator_intercepting(self, env):
        def disable_op(arg):
            raise TemplateRuntimeError("that operator so does not work")

        for expr, ctx, rv in ("-1", {}, "-1"), ("-a", {"a": 2}, "-2"):
            env = SandboxedEnvironment()
            env.unop_table["-"] = disable_op
            t = env.from_string(f"{{{{ {expr} }}}}")
            assert t.render(ctx) == rv
            env.intercepted_unops = frozenset(["-"])
            t = env.from_string(f"{{{{ {expr} }}}}")
            with pytest.raises(TemplateRuntimeError):
                t.render(ctx)


class TestStringFormat:
    def test_basic_format_safety(self):
        env = SandboxedEnvironment()
        t = env.from_string('{{ "a{0.__class__}b".format(42) }}')
        assert t.render() == "ab"

    def test_basic_format_all_okay(self):
        env = SandboxedEnvironment()
        t = env.from_string('{{ "a{0.foo}b".format({"foo": 42}) }}')
        assert t.render() == "a42b"

    def test_safe_format_safety(self):
        env = SandboxedEnvironment()
        t = env.from_string('{{ ("a{0.__class__}b{1}"|safe).format(42, "<foo>") }}')
        assert t.render() == "ab&lt;foo&gt;"

    def test_safe_format_all_okay(self):
        env = SandboxedEnvironment()
        t = env.from_string('{{ ("a{0.foo}b{1}"|safe).format({"foo": 42}, "<foo>") }}')
        assert t.render() == "a42b&lt;foo&gt;"

    def test_empty_braces_format(self):
        env = SandboxedEnvironment()
        t1 = env.from_string('{{ ("a{}b{}").format("foo", "42")}}')
        t2 = env.from_string('{{ ("a{}b{}"|safe).format(42, "<foo>") }}')
        assert t1.render() == "afoob42"
        assert t2.render() == "a42b&lt;foo&gt;"


class TestStringFormatMap:
    def test_basic_format_safety(self):
        env = SandboxedEnvironment()
        t = env.from_string('{{ "a{x.__class__}b".format_map({"x":42}) }}')
        assert t.render() == "ab"

    def test_basic_format_all_okay(self):
        env = SandboxedEnvironment()
        t = env.from_string('{{ "a{x.foo}b".format_map({"x":{"foo": 42}}) }}')
        assert t.render() == "a42b"

    def test_safe_format_all_okay(self):
        env = SandboxedEnvironment()
        t = env.from_string(
            '{{ ("a{x.foo}b{y}"|safe).format_map({"x":{"foo": 42}, "y":"<foo>"}) }}'
        )
        assert t.render() == "a42b&lt;foo&gt;"

    def test_indirect_call(self):
        def run(value, arg):
            return value.run(arg)

        env = SandboxedEnvironment()
        env.filters["run"] = run
        t = env.from_string(
            """{% set
                ns = namespace(run="{0.__call__.__builtins__[__import__]}".format)
            %}
            {{ ns | run(not_here) }}
            """
        )

        with pytest.raises(SecurityError):
            t.render()

    def test_attr_filter(self) -> None:
        env = SandboxedEnvironment()
        t = env.from_string(
            """{{ "{0.__call__.__builtins__[__import__]}"
                  | attr("format")(not_here) }}"""
        )

        with pytest.raises(SecurityError):
            t.render()


class _Counter:
    """Mutable counters shared by the instrumented objects."""

    def __init__(self) -> None:
        self.property_access = 0
        self.descriptor_access = 0
        self.getattr_calls = 0
        self.getattribute_calls = 0

    def assert_zero(self) -> None:
        assert self.property_access == 0
        assert self.descriptor_access == 0
        assert self.getattr_calls == 0
        assert self.getattribute_calls == 0


class _ExplodingProperty:
    """Data descriptor that counts every invocation and raises. If the name
    policy works, it must never run for a denied attribute."""

    def __get__(self, instance, owner=None):
        instance.counter.property_access += 1
        raise RuntimeError("denied property was executed")

    def __set__(self, instance, value) -> None:
        raise RuntimeError("denied property was assigned")


class _ExplodingDescriptor:
    """Non-data descriptor that counts every invocation and raises."""

    def __get__(self, instance, owner=None):
        instance.counter.descriptor_access += 1
        raise RuntimeError("denied descriptor was executed")


# Attribute names denied before any value is fetched.
DENIED_NAMES = frozenset({"secret", "denied_desc", "denied_dyn", "boom"})


class _GuardedObject:
    """Object whose denied attributes have observable side effects.

    ``secret`` is an exploding property, ``denied_desc`` an exploding
    non-data descriptor, and ``denied_dyn`` / ``boom`` are only reachable
    through ``__getattr__``. ``__getattribute__`` is counted too, so a test
    can prove the lookup machinery was never entered.
    """

    secret = _ExplodingProperty()
    denied_desc = _ExplodingDescriptor()

    def __init__(self, counter: _Counter) -> None:
        self.counter = counter

    @property
    def allowed_prop(self) -> str:
        return "allowed-value"

    plain = "plain-value"

    def __getattribute__(self, name):
        # Bypass this override when reaching for the counter itself.
        counter = object.__getattribute__(self, "counter")
        counter.getattribute_calls += 1
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        self.counter.getattr_calls += 1
        raise AttributeError(name)


class NamePolicySandbox(SandboxedEnvironment):
    """Denies the names in DENIED_NAMES before fetching a value."""

    def is_safe_attribute_name(self, obj, attr):
        return attr not in DENIED_NAMES


class TestAttributeNamePolicy:
    """Regression tests for the pre-fetch ``is_safe_attribute_name`` hook.

    Every denied access must return an unsafe undefined without the
    instrumented property, descriptor or ``__getattr__`` running once.
    """

    @pytest.fixture
    def counter(self):
        return _Counter()

    @pytest.fixture
    def env(self):
        return NamePolicySandbox()

    @pytest.fixture
    def obj(self, counter):
        return _GuardedObject(counter)

    @pytest.mark.parametrize("name", sorted(DENIED_NAMES))
    def test_dot_access_denied_before_fetch(self, env, obj, counter, name):
        out = env.from_string(f"{{{{ obj.{name} }}}}").render(obj=obj)
        assert out == ""
        counter.assert_zero()

    @pytest.mark.parametrize("name", sorted(DENIED_NAMES))
    def test_getitem_attribute_fallback_denied_before_fetch(
        self, env, obj, counter, name
    ):
        # The object is not subscriptable, so getitem falls back to attribute
        # access; the name policy must stop that fallback before getattr.
        out = env.from_string("{{ obj[name] }}").render(obj=obj, name=name)
        assert out == ""
        counter.assert_zero()

    def test_dict_key_still_works_through_subscription(self, env, counter):
        data = {"secret": "business-key-value", "foo": 42}
        out = env.from_string("{{ data['secret'] }}|{{ data['foo'] }}").render(
            data=data
        )
        assert out == "business-key-value|42"
        counter.assert_zero()

    def test_denied_dot_does_not_fall_back_to_dict_key(self, env, counter):
        data = {"secret": "business-key-value"}
        out = env.from_string("{{ data.secret }}").render(data=data)
        assert out == ""
        counter.assert_zero()
        # The same name remains reachable as an item.
        assert (
            env.from_string("{{ data['secret'] }}").render(data=data)
            == "business-key-value"
        )

    @pytest.mark.parametrize("name", ["secret", "denied_desc", "denied_dyn"])
    def test_attr_filter_probe_does_not_fetch(self, env, obj, counter, name):
        out = env.from_string("{{ obj|attr(name) }}").render(obj=obj, name=name)
        assert out == ""
        counter.assert_zero()

    def test_attr_filter_allowed_attribute_still_works(self, env, obj, counter):
        out = env.from_string('{{ obj|attr("allowed_prop") }}').render(obj=obj)
        assert out == "allowed-value"
        assert counter.property_access == 0

    def test_map_selectattr_rejectattr_denied_before_fetch(
        self, env, obj, counter
    ):
        items = [obj, obj]
        out = (
            env.from_string("{{ items|map(attribute='secret')|join('|') }}")
            .render(items=items)
        )
        assert out == "|"
        counter.assert_zero()

        out = (
            env.from_string("{{ items|selectattr('secret')|list|length }}")
            .render(items=items)
        )
        assert out == "0"
        counter.assert_zero()

        out = (
            env.from_string("{{ items|rejectattr('secret')|list|length }}")
            .render(items=items)
        )
        assert out == "2"
        counter.assert_zero()

    def test_map_allowed_attribute_still_works(self, env, obj):
        items = [obj, obj]
        out = (
            env.from_string(
                "{{ items|map(attribute='allowed_prop')|join('|') }}"
            ).render(items=items)
        )
        assert out == "allowed-value|allowed-value"

    def test_str_format_denied_field_before_fetch(self, env, obj, counter):
        out = env.from_string('{{ "{0.secret}".format(obj) }}').render(obj=obj)
        assert out == ""
        counter.assert_zero()

    def test_str_format_map_denied_field_before_fetch(self, env, obj, counter):
        out = env.from_string(
            '{{ "{x.secret}".format_map({"x": obj}) }}'
        ).render(obj=obj)
        assert out == ""
        counter.assert_zero()

    def test_format_allowed_field_and_item_still_work(self, env, obj):
        out = env.from_string(
            '{{ "{0.allowed_prop}|{0[plain]}".format(obj) }}'
        ).render(obj=obj)
        assert out == "allowed-value|plain-value"

    def test_denied_attribute_is_strict_undefined(self, obj, counter):
        env = NamePolicySandbox(undefined=StrictUndefined)
        with pytest.raises(SecurityError):
            env.from_string("{{ obj.secret }}").render(obj=obj)
        counter.assert_zero()

    def test_allowed_attributes_and_plain_undefined_unchanged(
        self, env, obj, counter
    ):
        out = env.from_string(
            "{{ obj.allowed_prop }}|{{ obj.plain }}|{{ obj.missing }}"
        ).render(obj=obj)
        assert out == "allowed-value|plain-value|"
        # Allowed lookups do go through the normal machinery.
        assert counter.getattribute_calls > 0
        assert counter.property_access == 0
        assert counter.descriptor_access == 0

    def test_post_fetch_safety_checks_still_apply(self, env, obj, counter):
        # Private / internal attributes remain blocked by is_safe_attribute.
        assert env.from_string("{{ obj.__class__ }}").render(obj=obj) == ""
        with pytest.raises(SecurityError):
            env.from_string("{{ obj.__class__.__subclasses__() }}").render(obj=obj)
        # The underscore names are only rejected after fetching, but none of
        # the instrumented side effects may fire.
        assert counter.property_access == 0
        assert counter.descriptor_access == 0
        assert counter.getattr_calls == 0

    def test_unsafe_undefined_uses_denied_name(self, env, obj):
        rv = env.getattr(obj, "secret")
        assert isinstance(rv, Undefined)
        assert rv._undefined_name == "secret"
        assert rv._undefined_exception is SecurityError
        with pytest.raises(SecurityError) as exc_info:
            rv._fail_with_undefined_error()
        assert "'secret'" in str(exc_info.value)

    def test_default_hook_allows_everything(self, counter):
        # Without an override, the instrumented property runs as before.
        env = SandboxedEnvironment()
        obj = _GuardedObject(counter)
        with pytest.raises(RuntimeError):
            env.from_string("{{ obj.secret }}").render(obj=obj)
        assert counter.property_access == 1

    def test_plain_environment_has_no_hook(self, counter):
        env = Environment()
        assert not hasattr(env, "is_safe_attribute_name")
        obj = _GuardedObject(counter)
        with pytest.raises(RuntimeError):
            env.from_string("{{ obj.secret }}").render(obj=obj)
        assert counter.property_access == 1


class TestAttributeNamePolicyAsync:
    @pytest.fixture
    def counter(self):
        return _Counter()

    @pytest.fixture
    def env(self):
        return NamePolicySandbox(enable_async=True)

    @pytest.fixture
    def obj(self, counter):
        return _GuardedObject(counter)

    def test_async_denied_accesses(self, env, obj, counter, run_async_fn):
        async def test():
            templates = [
                "{{ obj.secret }}",
                "{{ obj['denied_dyn'] }}",
                "{{ obj|attr('denied_desc') }}",
                "{{ [obj]|map(attribute='secret')|join('') }}",
                '{{ "{0.secret}".format(obj) }}',
                '{{ "{x.secret}".format_map({"x": obj}) }}',
            ]
            results = []
            for source in templates:
                results.append(
                    await env.from_string(source).render_async(obj=obj)
                )
            return results

        assert run_async_fn(test) == [""] * 6
        counter.assert_zero()

    def test_async_allowed_access(self, env, obj, run_async_fn):
        async def test():
            return await env.from_string(
                "{{ obj.allowed_prop }}"
            ).render_async(obj=obj)

        assert run_async_fn(test) == "allowed-value"


class TestPostFetchPolicyStillWired:
    def test_is_safe_attribute_can_still_reject_fetched_value(self):
        # The name hook allows "blocked", but the value hook rejects it,
        # proving the two stages are independent.
        class PostFetchSandbox(SandboxedEnvironment):
            def is_safe_attribute(self, obj, attr, value):
                if attr == "blocked":
                    return False
                return super().is_safe_attribute(obj, attr, value)

        class Target:
            blocked = "value"
            allowed = "value"

        env = PostFetchSandbox()
        target = Target()
        assert env.from_string("{{ obj.blocked }}").render(obj=target) == ""
        assert env.from_string("{{ obj.allowed }}").render(obj=target) == "value"
