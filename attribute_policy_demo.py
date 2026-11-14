"""Example: block side-effecting attributes before they are fetched.

Drop-in pattern for an existing template service: subclass
``SandboxedEnvironment`` and override ``is_safe_attribute_name`` to deny
attribute *names* before Jinja calls ``getattr``. Properties, descriptors and
``__getattr__`` on a denied name never run, so no query is issued and no audit
row is written. The post-fetch ``is_safe_attribute`` hook keeps doing its
original private/internal/callable filtering.
"""

from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment

# Names that must never be resolved as attributes on business objects.
DENIED_ATTRIBUTE_NAMES = frozenset({"secret", "audit_log", "lazy_report"})


class TemplateServiceEnvironment(SandboxedEnvironment):
    def is_safe_attribute_name(self, obj, attr):
        # Deny by name before any descriptor / property / __getattr__ runs.
        if attr in DENIED_ATTRIBUTE_NAMES:
            return False
        return True


class UserRecord:
    """A model whose sensitive attributes perform work when touched."""

    def __init__(self):
        self.name = "ada"
        self.audit_rows = []

    @property
    def secret(self):
        # In a real service this would query a secrets backend.
        self.audit_rows.append("secret accessed")
        raise RuntimeError("secrets backend must never be reached")

    @property
    def lazy_report(self):
        self.audit_rows.append("report query executed")
        return "report"

    def __getattr__(self, name):
        # Dynamic fallback that would also write an audit record.
        if name == "audit_log":
            self.audit_rows.append("audit log read")
            return ("row-1", "row-2")
        raise AttributeError(name)


env = TemplateServiceEnvironment()
strict_env = TemplateServiceEnvironment(undefined=StrictUndefined)
user = UserRecord()


def render(source, **ctx):
    return env.from_string(source).render(**ctx)


print("== denied attribute via dot access ==")
# Renders empty (default Undefined); the property never executed.
print(repr(render("{{ user.secret }}", user=user)))

print("== denied attribute via subscription fallback ==")
print(repr(render("{{ user['secret'] }}", user=user)))

print("== denied attribute via the attr filter ==")
print(repr(render("{{ user|attr('audit_log') }}", user=user)))

print("== denied attribute via map / selectattr ==")
print(repr(render("{{ [user]|map(attribute='lazy_report')|list }}", user=user)))
print(repr(render("{{ [user]|selectattr('secret')|list|length }}", user=user)))

print("== denied attribute via str.format / format_map ==")
print(repr(render('{{ "{0.secret}".format(user) }}', user=user)))
print(repr(render('{{ "{x.secret}".format_map({"x": user}) }}', user=user)))

print("== same-name dict key is still reachable as an item ==")
payload = {"secret": "business-data-key", "name": "ada"}
print(repr(render("{{ payload['secret'] }}", payload=payload)))
# ...but the dot request stays denied and must not fall back to that key.
print(repr(render("{{ payload.secret }}", payload=payload)))

print("== allowed attributes keep working ==")
print(repr(render("{{ user.name }}", user=user)))

print("== StrictUndefined turns the denial into a SecurityError ==")
try:
    strict_env.from_string("{{ user.secret }}").render(user=user)
except SecurityError as e:
    print(f"SecurityError: {e}")

print("== side-effect ledger (must stay empty) ==")
print(user.audit_rows)
assert user.audit_rows == [], "a denied attribute triggered a side effect!"
print("OK: no query ran, no audit row written.")
