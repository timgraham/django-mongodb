import sys
from unittest import expectedFailure

from django.db import Error, IntegrityError, connection
from django.test import TransactionTestCase, skipIfDBFeature, skipUnlessDBFeature

from django_mongodb_backend import transaction

from .models import Reporter


@skipUnlessDBFeature("_supports_transactions")
class AtomicTests(TransactionTestCase):
    """
    Tests for the atomic decorator and context manager.

    The tests make assertions on internal attributes because there isn't a
    robust way to ask the database for its current transaction state.

    Since the decorator syntax is converted into a context manager (see the
    implementation), there are only a few basic tests with the decorator
    syntax and the bulk of the tests use the context manager syntax.
    """

    available_apps = ["transactions_"]

    def test_decorator_syntax_commit(self):
        @transaction.atomic
        def make_reporter():
            return Reporter.objects.create(first_name="Tintin")

        reporter = make_reporter()
        self.assertSequenceEqual(Reporter.objects.all(), [reporter])

    def test_decorator_syntax_rollback(self):
        @transaction.atomic
        def make_reporter():
            Reporter.objects.create(first_name="Haddock")
            raise Exception("Oops, that's his last name")

        with self.assertRaisesMessage(Exception, "Oops"):
            make_reporter()
        self.assertSequenceEqual(Reporter.objects.all(), [])

    def test_alternate_decorator_syntax_commit(self):
        @transaction.atomic()
        def make_reporter():
            return Reporter.objects.create(first_name="Tintin")

        reporter = make_reporter()
        self.assertSequenceEqual(Reporter.objects.all(), [reporter])

    def test_alternate_decorator_syntax_rollback(self):
        @transaction.atomic()
        def make_reporter():
            Reporter.objects.create(first_name="Haddock")
            raise Exception("Oops, that's his last name")

        with self.assertRaisesMessage(Exception, "Oops"):
            make_reporter()
        self.assertSequenceEqual(Reporter.objects.all(), [])

    def test_commit(self):
        with transaction.atomic():
            reporter = Reporter.objects.create(first_name="Tintin")
        self.assertSequenceEqual(Reporter.objects.all(), [reporter])

    def test_rollback(self):
        with self.assertRaisesMessage(Exception, "Oops"), transaction.atomic():
            Reporter.objects.create(first_name="Haddock")
            raise Exception("Oops, that's his last name")
        self.assertSequenceEqual(Reporter.objects.all(), [])

    def test_nested_commit_commit(self):
        with transaction.atomic():
            reporter1 = Reporter.objects.create(first_name="Tintin")
            with transaction.atomic():
                reporter2 = Reporter.objects.create(first_name="Archibald", last_name="Haddock")
        self.assertSequenceEqual(Reporter.objects.all(), [reporter2, reporter1])

    @expectedFailure
    def test_nested_commit_rollback(self):
        with transaction.atomic():
            reporter = Reporter.objects.create(first_name="Tintin")
            with self.assertRaisesMessage(Exception, "Oops"), transaction.atomic():
                Reporter.objects.create(first_name="Haddock")
                raise Exception("Oops, that's his last name")
        self.assertSequenceEqual(Reporter.objects.all(), [reporter])

    def test_nested_rollback_commit(self):
        with self.assertRaisesMessage(Exception, "Oops"), transaction.atomic():
            Reporter.objects.create(last_name="Tintin")
            with transaction.atomic():
                Reporter.objects.create(last_name="Haddock")
            raise Exception("Oops, that's his first name")
        self.assertSequenceEqual(Reporter.objects.all(), [])

    def test_nested_rollback_rollback(self):
        with self.assertRaisesMessage(Exception, "Oops"), transaction.atomic():
            Reporter.objects.create(last_name="Tintin")
            with self.assertRaisesMessage(Exception, "Oops"):
                with transaction.atomic():
                    Reporter.objects.create(first_name="Haddock")
                raise Exception("Oops, that's his last name")
            raise Exception("Oops, that's his first name")
        self.assertSequenceEqual(Reporter.objects.all(), [])

    def test_reuse_commit_commit(self):
        atomic = transaction.atomic()
        with atomic:
            reporter1 = Reporter.objects.create(first_name="Tintin")
            with atomic:
                reporter2 = Reporter.objects.create(first_name="Archibald", last_name="Haddock")
        self.assertSequenceEqual(Reporter.objects.all(), [reporter2, reporter1])

    @expectedFailure
    def test_reuse_commit_rollback(self):
        atomic = transaction.atomic()
        with atomic:
            reporter = Reporter.objects.create(first_name="Tintin")
            with self.assertRaisesMessage(Exception, "Oops"), atomic:
                Reporter.objects.create(first_name="Haddock")
                raise Exception("Oops, that's his last name")
        self.assertSequenceEqual(Reporter.objects.all(), [reporter])

    def test_reuse_rollback_commit(self):
        atomic = transaction.atomic()
        with self.assertRaisesMessage(Exception, "Oops"), atomic:
            Reporter.objects.create(last_name="Tintin")
            with atomic:
                Reporter.objects.create(last_name="Haddock")
            raise Exception("Oops, that's his first name")
        self.assertSequenceEqual(Reporter.objects.all(), [])

    def test_reuse_rollback_rollback(self):
        atomic = transaction.atomic()
        with self.assertRaisesMessage(Exception, "Oops"), atomic:
            Reporter.objects.create(last_name="Tintin")
            with self.assertRaisesMessage(Exception, "Oops"):
                with atomic:
                    Reporter.objects.create(first_name="Haddock")
                raise Exception("Oops, that's his last name")
            raise Exception("Oops, that's his first name")
        self.assertSequenceEqual(Reporter.objects.all(), [])


class AtomicInsideTransactionTests(AtomicTests):
    """All basic tests for atomic should also pass within an existing transaction."""

    def setUp(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()

    def tearDown(self):
        self.atomic.__exit__(*sys.exc_info())


@skipUnlessDBFeature("uses_savepoints")
class AtomicErrorsTests(TransactionTestCase):
    available_apps = ["transactions"]
    forbidden_atomic_msg = "This is forbidden when an 'atomic' block is active."

    def test_atomic_prevents_setting_autocommit(self):
        autocommit = transaction.get_autocommit()
        with (
            transaction.atomic(),
            self.assertRaisesMessage(
                transaction.TransactionManagementError, self.forbidden_atomic_msg
            ),
        ):
            transaction.set_autocommit(not autocommit)
        # Make sure autocommit wasn't changed.
        self.assertEqual(connection.autocommit, autocommit)

    def test_atomic_prevents_calling_transaction_methods(self):
        with transaction.atomic():
            with self.assertRaisesMessage(
                transaction.TransactionManagementError, self.forbidden_atomic_msg
            ):
                transaction.commit()
            with self.assertRaisesMessage(
                transaction.TransactionManagementError, self.forbidden_atomic_msg
            ):
                transaction.rollback()

    def test_atomic_prevents_queries_in_broken_transaction(self):
        r1 = Reporter.objects.create(first_name="Archibald", last_name="Haddock")
        with transaction.atomic():
            r2 = Reporter(first_name="Cuthbert", last_name="Calculus", id=r1.id)
            with self.assertRaises(IntegrityError):
                r2.save(force_insert=True)
            # The transaction is marked as needing rollback.
            msg = (
                "An error occurred in the current transaction. You can't "
                "execute queries until the end of the 'atomic' block."
            )
            with self.assertRaisesMessage(transaction.TransactionManagementError, msg) as cm:
                r2.save(force_update=True)
        self.assertIsInstance(cm.exception.__cause__, IntegrityError)
        self.assertEqual(Reporter.objects.get(pk=r1.pk).last_name, "Haddock")

    @skipIfDBFeature("atomic_transactions")
    def test_atomic_allows_queries_after_fixing_transaction(self):
        r1 = Reporter.objects.create(first_name="Archibald", last_name="Haddock")
        with transaction.atomic():
            r2 = Reporter(first_name="Cuthbert", last_name="Calculus", id=r1.id)
            with self.assertRaises(IntegrityError):
                r2.save(force_insert=True)
            # Mark the transaction as no longer needing rollback.
            transaction.set_rollback(False)
            r2.save(force_update=True)
        self.assertEqual(Reporter.objects.get(pk=r1.pk).last_name, "Calculus")

    @skipUnlessDBFeature("test_db_allows_multiple_connections")
    def test_atomic_prevents_queries_in_broken_transaction_after_client_close(self):
        with transaction.atomic():
            Reporter.objects.create(first_name="Archibald", last_name="Haddock")
            connection.close()
            # The connection is closed and the transaction is marked as
            # needing rollback. This will raise an InterfaceError on databases
            # that refuse to create cursors on closed connections (PostgreSQL)
            # and a TransactionManagementError on other databases.
            with self.assertRaises(Error):
                Reporter.objects.create(first_name="Cuthbert", last_name="Calculus")
        # The connection is usable again .
        self.assertEqual(Reporter.objects.count(), 0)


# class AtomicMiscTests(TransactionTestCase):
#    available_apps = ["transactions"]

#    def test_wrap_callable_instance(self):
#        """#20028 -- Atomic must support wrapping callable instances."""

#        class Callable:
#            def __call__(self):
#                pass

#        # Must not raise an exception
#        transaction.atomic(Callable())

#    @skipUnlessDBFeature("can_release_savepoints")
#    def test_atomic_does_not_leak_savepoints_on_failure(self):
#        """#23074 -- Savepoints must be released after rollback."""

#        # Expect an error when rolling back a savepoint that doesn't exist.
#        # Done outside of the transaction block to ensure proper recovery.
#        with self.assertRaises(Error):
#            # Start a plain transaction.
#            with transaction.atomic():
#                # Swallow the intentional error raised in the sub-transaction.
#                with self.assertRaisesMessage(Exception, "Oops"):
#                    # Start a sub-transaction with a savepoint.
#                    with transaction.atomic():
#                        sid = connection.savepoint_ids[-1]
#                        raise Exception("Oops")

#                # This is expected to fail because the savepoint no longer exists.
#                connection.savepoint_rollback(sid)

#    @skipUnlessDBFeature("supports_transactions")
#    def test_mark_for_rollback_on_error_in_transaction(self):
#        with transaction.atomic(savepoint=False):
#            # Swallow the intentional error raised.
#            with self.assertRaisesMessage(Exception, "Oops"):
#                # Wrap in `mark_for_rollback_on_error` to check if the
#                # transaction is marked broken.
#                with transaction.mark_for_rollback_on_error():
#                    # Ensure that we are still in a good state.
#                    self.assertFalse(transaction.get_rollback())

#                    raise Exception("Oops")

#                # mark_for_rollback_on_error marked the transaction as broken …
#                self.assertTrue(transaction.get_rollback())

#            # … and further queries fail.
#            msg = "You can't execute queries until the end of the 'atomic' block."
#            with self.assertRaisesMessage(transaction.TransactionManagementError, msg):
#                Reporter.objects.create()

#        # Transaction errors are reset at the end of an transaction, so this
#        # should just work.
#        Reporter.objects.create()

#    def test_mark_for_rollback_on_error_in_autocommit(self):
#        self.assertTrue(transaction.get_autocommit())

#        # Swallow the intentional error raised.
#        with self.assertRaisesMessage(Exception, "Oops"):
#            # Wrap in `mark_for_rollback_on_error` to check if the transaction
#            # is marked broken.
#            with transaction.mark_for_rollback_on_error():
#                # Ensure that we are still in a good state.
#                self.assertFalse(transaction.get_connection().needs_rollback)

#                raise Exception("Oops")

#            # Ensure that `mark_for_rollback_on_error` did not mark the transaction
#            # as broken, since we are in autocommit mode …
#            self.assertFalse(transaction.get_connection().needs_rollback)

#        # … and further queries work nicely.
#        Reporter.objects.create()


# @skipUnlessDBFeature("supports_transactions")
# class NonAutocommitTests(TransactionTestCase):
#    available_apps = []

#    def setUp(self):
#        transaction.set_autocommit(False)
#        self.addCleanup(transaction.set_autocommit, True)
#        self.addCleanup(transaction.rollback)

#    def test_orm_query_after_error_and_rollback(self):
#        """
#        ORM queries are allowed after an error and a rollback in non-autocommit
#        mode (#27504).
#        """
#        r1 = Reporter.objects.create(first_name="Archibald", last_name="Haddock")
#        r2 = Reporter(first_name="Cuthbert", last_name="Calculus", id=r1.id)
#        with self.assertRaises(IntegrityError):
#            r2.save(force_insert=True)
#        transaction.rollback()
#        Reporter.objects.last()

#    def test_orm_query_without_autocommit(self):
#        """#24921 -- ORM queries must be possible after set_autocommit(False)."""
#        Reporter.objects.create(first_name="Tintin")


# class DurableTestsBase:
#    available_apps = ["transactions"]

#    def test_commit(self):
#        with transaction.atomic(durable=True):
#            reporter = Reporter.objects.create(first_name="Tintin")
#        self.assertEqual(Reporter.objects.get(), reporter)

#    def test_nested_outer_durable(self):
#        with transaction.atomic(durable=True):
#            reporter1 = Reporter.objects.create(first_name="Tintin")
#            with transaction.atomic():
#                reporter2 = Reporter.objects.create(
#                    first_name="Archibald",
#                    last_name="Haddock",
#                )
#        self.assertSequenceEqual(Reporter.objects.all(), [reporter2, reporter1])

#    def test_nested_both_durable(self):
#        msg = "A durable atomic block cannot be nested within another atomic block."
#        with transaction.atomic(durable=True):
#            with self.assertRaisesMessage(RuntimeError, msg):
#                with transaction.atomic(durable=True):
#                    pass

#    def test_nested_inner_durable(self):
#        msg = "A durable atomic block cannot be nested within another atomic block."
#        with transaction.atomic():
#            with self.assertRaisesMessage(RuntimeError, msg):
#                with transaction.atomic(durable=True):
#                    pass

#    def test_sequence_of_durables(self):
#        with transaction.atomic(durable=True):
#            reporter = Reporter.objects.create(first_name="Tintin 1")
#        self.assertEqual(Reporter.objects.get(first_name="Tintin 1"), reporter)
#        with transaction.atomic(durable=True):
#            reporter = Reporter.objects.create(first_name="Tintin 2")
#        self.assertEqual(Reporter.objects.get(first_name="Tintin 2"), reporter)


# class DurableTransactionTests(DurableTestsBase, TransactionTestCase):
#    pass


# class DurableTests(DurableTestsBase, TestCase):
#    pass
