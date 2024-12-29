from django.db import connection
from django.db.migrations.state import ProjectState
from migrations.test_base import OperationTestBase

from django_mongodb.migrations import RunMQL


def create_collection(schema_editor, database):  # noqa: ARG001
    database.create_collection("test_runmql")


def drop_collection(schema_editor, database):  # noqa: ARG001
    database.drop_collection("test_runmql")


class RunMQLTests(OperationTestBase):
    available_apps = ["migrations_"]

    def test_basic(self):
        project_state = ProjectState()
        operation = RunMQL(create_collection, reverse_code=drop_collection)
        self.assertEqual(operation.describe(), "Raw MQL operation")
        # Test the state alteration does nothing
        new_state = project_state.clone()
        operation.state_forwards("test_runmql", new_state)
        self.assertEqual(new_state, project_state)
        # Test the database alteration
        self.assertTableNotExists("test_runmql")
        with connection.schema_editor() as editor:
            operation.database_forwards("test_runmql", editor, project_state, new_state)
        self.assertTableExists("test_runmql")
        # Now test reversal
        self.assertTrue(operation.reversible)
        with connection.schema_editor() as editor:
            operation.database_backwards("test_runmql", editor, project_state, new_state)
        self.assertTableNotExists("test_runmql")
        # Test deconstruction
        definition = operation.deconstruct()
        self.assertEqual(definition[0], "RunMQL")
        self.assertEqual(definition[1], [])
        self.assertEqual(sorted(definition[2]), ["code", "reverse_code"])
        # Also test reversal fails, with an operation identical to above but
        # without reverse_code set.
        no_reverse_operation = RunMQL(create_collection)
        self.assertFalse(no_reverse_operation.reversible)
        with connection.schema_editor() as editor:
            no_reverse_operation.database_forwards("test_runmql", editor, project_state, new_state)
            with self.assertRaises(NotImplementedError):
                no_reverse_operation.database_backwards(
                    "test_runmql", editor, new_state, project_state
                )
        self.assertTableExists("test_runmql")

    def test_run_msql_no_reverse(self):
        project_state = ProjectState()
        new_state = project_state.clone()
        operation = RunMQL(create_collection)
        self.assertTableNotExists("test_runmql")
        with connection.schema_editor() as editor:
            operation.database_forwards("test_runmql", editor, project_state, new_state)
        self.assertTableExists("test_runmql")
        # And deconstruction
        definition = operation.deconstruct()
        self.assertEqual(definition[0], "RunMQL")
        self.assertEqual(definition[1], [])
        self.assertEqual(sorted(definition[2]), ["code"])

    def test_elidable(self):
        operation = RunMQL(create_collection)
        self.assertIs(operation.reduce(operation, []), False)
        elidable_operation = RunMQL(create_collection, elidable=True)
        self.assertEqual(elidable_operation.reduce(operation, []), [operation])

    def test_run_mql_invalid_code(self):
        with self.assertRaisesMessage(ValueError, "RunMQL must be supplied with a callable"):
            RunMQL("print 'ahahaha'")
