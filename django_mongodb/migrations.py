from django.db import router
from django.db.migrations.operations.base import Operation


class RunMQL(Operation):
    """
    Run a function that can execute some raw queries. A reverse function may
    be also provided.

    Also accept a list of operations that represent the state change effected
    by this MQL change, in case it's custom column/table creation/deletion.
    """

    noop = ""

    def __init__(self, code, reverse_code=None, state_operations=None, hints=None, elidable=False):
        # Forwards code
        if not callable(code):
            raise ValueError("RunMQL must be supplied with a callable")
        self.code = code
        # Reverse code
        self.reverse_code = reverse_code
        if reverse_code is not None and not callable(reverse_code):
            raise ValueError("RunMQL must be supplied with callable arguments")
        self.state_operations = state_operations or []
        self.hints = hints or {}
        self.elidable = elidable

    def deconstruct(self):
        kwargs = {"code": self.code}
        if self.reverse_code is not None:
            kwargs["reverse_code"] = self.reverse_code
        if self.state_operations:
            kwargs["state_operations"] = self.state_operations
        if self.hints:
            kwargs["hints"] = self.hints
        return (self.__class__.__qualname__, [], kwargs)

    @property
    def reversible(self):
        return self.reverse_code is not None

    def state_forwards(self, app_label, state):
        for state_operation in self.state_operations:
            state_operation.state_forwards(app_label, state)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if router.allow_migrate(schema_editor.connection.alias, app_label, **self.hints):
            self.code(schema_editor, schema_editor.get_database())

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if self.reverse_code is None:
            raise NotImplementedError("You cannot reverse this operation")
        if router.allow_migrate(schema_editor.connection.alias, app_label, **self.hints):
            self.reverse_code(schema_editor, schema_editor.get_database())

    def describe(self):
        return "Raw MQL operation"
