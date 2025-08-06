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

    An atomic block can be tagged as durable. In this case, a RuntimeError is
    raised if it's nested within another atomic block. This guarantees
    that database changes in a durable block are committed to the database when
    the block exits without error.
    """

    def __init__(self, using, durable):
        self.using = using
        self.durable = durable

    def __enter__(self):
        connection = get_connection(self.using)

        if self.durable and connection.atomic_blocks_mongo:
            raise RuntimeError(
                "A durable atomic block cannot be nested within another atomic block."
            )
        if not connection.in_atomic_block_mongo:
            # Reset state when entering an outermost atomic block.
            connection.commit_on_exit_mongo = True
            connection.needs_rollback_mongo = False
            #            if not connection.get_autocommit():
            # Pretend we're already in an atomic block to bypass the code
            # that disables autocommit to enter a transaction, and make a
            # note to deal with this case in __exit__.
            # connection.in_atomic_block_mongo = True
            # connection.commit_on_exit = False

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
            # Outermost block exit when autocommit was enabled.
            if not connection.in_atomic_block_mongo:
                pass
            # connection.set_autocommit(True)
            # Outermost block exit when autocommit was disabled.
            elif not connection.commit_on_exit:
                connection.in_atomic_block_mongo = False


def atomic(using=None, durable=False):
    # Bare decorator: @atomic -- although the first argument is called
    # `using`, it's actually the function being decorated.
    if callable(using):
        return Atomic(DEFAULT_DB_ALIAS, durable)(using)
    # Decorator: @atomic(...) or context manager: with atomic(...): ...
    return Atomic(using, durable)
