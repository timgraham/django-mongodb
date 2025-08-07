from contextlib import ContextDecorator

from django.db import DEFAULT_DB_ALIAS, DatabaseError, Error
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
    """

    def __init__(self, using):
        self.using = using

    def __enter__(self):
        connection = get_connection(self.using)
        if not connection.in_atomic_block_mongo:
            # Reset state when entering an outermost atomic block.
            connection.needs_rollback_mongo = False

        if connection.in_atomic_block_mongo:
            # We're already in a transaction. Increment the number of nested atomics.
            connection.nested_atomics += 1
        else:
            connection._start_transaction()
            connection.in_atomic_block_mongo = True

        if connection.in_atomic_block_mongo:
            connection.atomic_blocks_mongo.append(self)

    def __exit__(self, exc_type, exc_value, traceback):
        connection = get_connection(self.using)

        if connection.in_atomic_block_mongo:
            connection.atomic_blocks_mongo.pop()

        if connection.nested_atomics:
            connection.nested_atomics -= 1
        else:
            # Prematurely unset this flag to allow using commit or rollback.
            connection.in_atomic_block_mongo = False
        try:
            if exc_type is None and not connection.needs_rollback_mongo:
                if connection.in_atomic_block_mongo:
                    # Release savepoint if there is one
                    pass
                else:
                    # Commit transaction
                    try:
                        connection.commit_mongo()
                    except DatabaseError:
                        try:
                            connection.rollback_mongo()
                        except Error:
                            # An error during rollback means that something
                            # went wrong with the connection. Drop it.
                            connection.close()
                        raise
            else:
                # This flag will be set to True again if there isn't a savepoint
                # allowing to perform the rollback at this level.
                connection.needs_rollback_mongo = False
                if connection.in_atomic_block_mongo:
                    # Mark for rollback
                    connection.needs_rollback_mongo = True
                else:
                    # Roll back transaction
                    try:
                        connection.rollback_mongo()
                    except Error:
                        # An error during rollback means that something
                        # went wrong with the connection. Drop it.
                        connection.close()
        finally:
            # Outermost block exit
            if (
                not connection.in_atomic_block_mongo
                and connection.run_commit_hooks_on_set_autocommit_on
            ):
                connection.run_and_clear_commit_hooks()


def atomic(using=None):
    # Bare decorator: @atomic -- although the first argument is called
    # `using`, it's actually the function being decorated.
    if callable(using):
        return Atomic(DEFAULT_DB_ALIAS)(using)
    # Decorator: @atomic(...) or context manager: with atomic(...): ...
    return Atomic(using)
