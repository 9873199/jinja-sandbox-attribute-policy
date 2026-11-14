import pytest
from jinja2 import Environment, Undefined
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment, unsafe

class Policy(SandboxedEnvironment):
    def is_safe_attribute_name(self,obj,attr):
        return attr != "secret"

class Subject:
    def __init__(self): self.accesses=[]
    @property
    def secret(self):
        self.accesses.append("property")
        raise RuntimeError("property must not execute")
    @property
    def allowed(self): return "visible"

class Missing:
    def __init__(self): self.accesses=[]
    def __getattr__(self,name):
        self.accesses.append(name)
        if name=="secret": raise RuntimeError("dynamic lookup must not execute")
        raise AttributeError(name)

BLOCKED=[
    "{{ obj.secret }}", "{{ obj['secret'] }}", "{{ obj|attr('secret') }}",
    "{{ items|map(attribute='secret')|list }}",
    "{{ items|selectattr('secret')|list }}",
    "{{ items|rejectattr('secret')|list }}",
    "{{ '{0.secret}'.format(obj) }}",
    "{{ '{obj.secret}'.format_map({'obj':obj}) }}",
    "{{ ('{0.secret}'|attr('format'))(obj) }}",
]
@pytest.mark.parametrize('expression',BLOCKED)
@pytest.mark.parametrize('kind',[Subject,Missing])
def test_denied_access_has_zero_side_effects(expression,kind):
    obj=kind()
    try: Policy().from_string(expression).render(obj=obj,items=[obj])
    except SecurityError: pass
    assert obj.accesses==[]

def test_denied_dot_cannot_fall_back_to_dictionary():
    e=Policy();obj={'secret':'not allowed by dot'}
    assert isinstance(e.getattr(obj,'secret'),Undefined)
    assert e.from_string("{{ obj.secret }}").render(obj=obj)==''
    assert e.from_string("{{ obj['secret'] }}").render(obj=obj)=='not allowed by dot'

def test_key_precedence_retained_for_attribute_filters():
    e=Policy();obj={'secret':'key-value'}
    assert e.from_string("{{ xs|map(attribute='secret')|join(',') }}").render(xs=[obj])=='key-value'
    assert e.from_string("{{ xs|selectattr('secret')|list|length }}").render(xs=[obj])=='1'

def test_allowed_property_and_missing_value():
    e=Policy();obj=Subject()
    assert e.from_string("{{ obj.allowed }}|{{ obj['allowed'] }}|{{ obj|attr('allowed') }}").render(obj=obj)=='visible|visible|visible'
    assert e.from_string("{{ obj.absent }}").render(obj=obj)==''
    assert obj.accesses==[]

def test_post_value_policy_still_applies():
    class Both(Policy):
        def is_safe_attribute(self,obj,attr,value): return attr!='allowed' and super().is_safe_attribute(obj,attr,value)
    assert isinstance(Both().getattr(Subject(),'allowed'),Undefined)
    assert isinstance(Policy().getattr(Subject(),'__class__'),Undefined)

def test_default_hook_and_ordinary_environment_keep_access():
    class Ordinary:
        def __init__(self): self.count=0
        @property
        def secret(self): self.count+=1; return 'ordinary'
    for e in (Environment(),SandboxedEnvironment()):
        obj=Ordinary();assert e.from_string('{{ obj.secret }}').render(obj=obj)=='ordinary';assert obj.count==1

def test_unsafe_callable_remains_rejected():
    @unsafe
    def execute(): return 'wrong'
    with pytest.raises(SecurityError): Policy().from_string('{{ execute() }}').render(execute=execute)
