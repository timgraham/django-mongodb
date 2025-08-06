from unittest import expectedFailure

from django.test import TransactionTestCase, skipUnlessDBFeature

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

    # class AtomicInsideTransactionTests(AtomicTests):
    #    """All basic tests for atomic should also pass within an existing transaction."""

    #    def setUp(self):
    #        self.atomic = transaction.atomic()
    #        self.atomic.__enter__()

    #    def tearDown(self):
    #        self.atomic.__exit__(*sys.exc_info())

    def test_wrap_callable_instance(self):
        """Atomic can wrap callable instances."""

        class Callable:
            def __call__(self):
                pass

        # Must not raise an exception
        transaction.atomic(Callable())


class DurableTests(TransactionTestCase):
    available_apps = ["transactions_"]

    def test_commit(self):
        with transaction.atomic(durable=True):
            reporter = Reporter.objects.create(first_name="Tintin")
        self.assertEqual(Reporter.objects.get(), reporter)

    def test_nested_outer_durable(self):
        with transaction.atomic(durable=True):
            reporter1 = Reporter.objects.create(first_name="Tintin")
            with transaction.atomic():
                reporter2 = Reporter.objects.create(
                    first_name="Archibald",
                    last_name="Haddock",
                )
        self.assertSequenceEqual(Reporter.objects.all(), [reporter2, reporter1])

    def test_nested_both_durable(self):
        msg = "A durable atomic block cannot be nested within another atomic block."
        with (
            transaction.atomic(durable=True),
            self.assertRaisesMessage(RuntimeError, msg),
            transaction.atomic(durable=True),
        ):
            pass

    def test_nested_inner_durable(self):
        msg = "A durable atomic block cannot be nested within another atomic block."
        with (
            transaction.atomic(),
            self.assertRaisesMessage(RuntimeError, msg),
            transaction.atomic(durable=True),
        ):
            pass

    def test_sequence_of_durables(self):
        with transaction.atomic(durable=True):
            reporter = Reporter.objects.create(first_name="Tintin 1")
        self.assertEqual(Reporter.objects.get(first_name="Tintin 1"), reporter)
        with transaction.atomic(durable=True):
            reporter = Reporter.objects.create(first_name="Tintin 2")
        self.assertEqual(Reporter.objects.get(first_name="Tintin 2"), reporter)
