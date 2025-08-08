from contextlib import ContextDecorator

from django.db import DEFAULT_DB_ALIAS, DatabaseError
from django.db.transaction import get_connection


def on_commit(func, using=None, robust=False):
    """
    Register `func` to be called when the current transaction is committed.
    If the current transaction is rolled back, `func` will not be called.
    """
    get_connection(using).on_commit(func, robust)


class Atomic(ContextDecorator):
    """
    Guarantee the atomic execution of a given block.

    An instance can be used either as a decorator or as a context manager.

    When it's used as a decorator, __call__ wraps the execution of the
    decorated function in the instance itself, used as a context manager.

    When it's used as a context manager, __enter__ creates a transaction and
    __exit__ commits the transaction on normal exit, and rolls back the transaction on
    exceptions.

    This allows reentrancy even if the same AtomicWrapper is reused. For
    example, it's possible to define `oa = atomic('other')` and use `@oa` or
    `with oa:` multiple times.

    Since database connections are thread-local, this is thread-safe.

    Simplified from django.db.transaction.
    """

    def __init__(self, using):
        self.using = using

    def __enter__(self):
        connection = get_connection(self.using)
        if connection.in_atomic_block_mongo:
            # If we're already in an atomic(), track the number of nested calls.
            connection.nested_atomics += 1
        else:
            # Start a transaction for the outermost atomic().
            connection._start_transaction()
            connection.in_atomic_block_mongo = True

    def __exit__(self, exc_type, exc_value, traceback):
        connection = get_connection(self.using)
        if connection.nested_atomics:
            connection.nested_atomics -= 1
        else:
            connection.in_atomic_block_mongo = False
        try:
            if exc_type is None:
                # atomic() exited without an error.
                if connection.in_atomic_block_mongo:
                    # Do nothing for an inner atomic().
                    pass
                else:
                    # Commit transaction.
                    try:
                        connection.commit_mongo()
                    except DatabaseError:
                        connection.rollback_mongo()
            else:
                # atomic() exited with an error.
                if connection.in_atomic_block_mongo:
                    # Do nothing for an inner atomic().
                    pass
                else:
                    # Rollback transaction.
                    connection.rollback_mongo()
        finally:
            if (
                not connection.in_atomic_block_mongo
                and connection.run_commit_hooks_on_set_autocommit_on
            ):
                # Run on_commit() callbacks after outermost atomic()
                connection.run_and_clear_commit_hooks()


def atomic(using=None):
    # Bare decorator: @atomic -- although the first argument is called `using`, it's
    # actually the function being decorated.
    if callable(using):
        return Atomic(DEFAULT_DB_ALIAS)(using)
    # Decorator: @atomic(...) or context manager: with atomic(...): ...
    return Atomic(using)
