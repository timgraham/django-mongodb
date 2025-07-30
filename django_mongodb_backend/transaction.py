from contextlib import ContextDecorator, contextmanager

from django.db import (
    DEFAULT_DB_ALIAS,
    DatabaseError,
    Error,
    ProgrammingError,
    connections,
)


class TransactionManagementError(ProgrammingError):
    """Transaction management is used improperly."""


def get_connection(using=None):
    """
    Get a database connection by name, or the default database connection
    if no name is provided. This is a private API.
    """
    if using is None:
        using = DEFAULT_DB_ALIAS
    return connections[using]


def get_autocommit(using=None):
    """Get the autocommit status of the connection."""
    return get_connection(using).get_autocommit()


def set_autocommit(autocommit, using=None):
    """Set the autocommit status of the connection."""
    return get_connection(using).set_autocommit(autocommit)


def commit(using=None):
    """Commit a transaction."""
    get_connection(using).commit()


def rollback(using=None):
    """Roll back a transaction."""
    get_connection(using).rollback()


def set_rollback(rollback, using=None):
    """
    Set or unset the "needs rollback" flag -- for *advanced use* only.

    When `rollback` is `True`, trigger a rollback when exiting the innermost
    enclosing atomic block that has `savepoint=True` (that's the default). Use
    this to force a rollback without raising an exception.

    When `rollback` is `False`, prevent such a rollback. Use this only after
    rolling back to a known-good state! Otherwise, you break the atomic block
    and data corruption may occur.
    """
    return get_connection(using).set_rollback(rollback)


@contextmanager
def mark_for_rollback_on_error(using=None):
    """
    Internal low-level utility to mark a transaction as "needs rollback" when
    an exception is raised while not enforcing the enclosed block to be in a
    transaction. This is needed by Model.save() and friends to avoid starting a
    transaction when in autocommit mode and a single query is executed.

    It's equivalent to:

        connection = get_connection(using)
        if connection.get_autocommit():
            yield
        else:
            with transaction.atomic(using=using, savepoint=False):
                yield

    but it uses low-level utilities to avoid performance overhead.
    """
    try:
        yield
    except Exception as exc:
        connection = get_connection(using)
        if connection.in_atomic_block:
            connection.needs_rollback = True
            connection.rollback_exc = exc
        raise


def on_commit(func, using=None, robust=False):
    """
    Register `func` to be called when the current transaction is committed.
    If the current transaction is rolled back, `func` will not be called.
    """
    get_connection(using).on_commit(func, robust)


#################################
# Decorators / context managers #
#################################


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

    This is a private API.
    """

    def __init__(self, using, durable):
        self.using = using
        self.durable = durable
        self._from_testcase = False

    def __enter__(self):
        connection = get_connection(self.using)

        if (
            self.durable
            and connection.atomic_blocks
            and not connection.atomic_blocks[-1]._from_testcase
        ):
            raise RuntimeError(
                "A durable atomic block cannot be nested within another " "atomic block."
            )
        if not connection.in_atomic_block:
            # Reset state when entering an outermost atomic block.
            connection.commit_on_exit = True
            connection.needs_rollback = False
            if not connection.get_autocommit():
                # Pretend we're already in an atomic block to bypass the code
                # that disables autocommit to enter a transaction, and make a
                # note to deal with this case in __exit__.
                connection.in_atomic_block = True
                connection.commit_on_exit = False

        if connection.in_atomic_block:
            # We're already in a transaction
            pass
        else:
            connection.set_autocommit(False, force_begin_transaction_with_broken_autocommit=True)
            connection.in_atomic_block = True

        if connection.in_atomic_block:
            connection.atomic_blocks.append(self)

    def __exit__(self, exc_type, exc_value, traceback):
        connection = get_connection(self.using)

        if connection.in_atomic_block:
            connection.atomic_blocks.pop()

        # Prematurely unset this flag to allow using commit or rollback.
        connection._in_atomic_block = False
        try:
            if connection._closed_in_transaction:
                # The database will perform a rollback by itself.
                # Wait until we exit the outermost block.
                pass

            elif exc_type is None and not connection._needs_rollback:
                if connection._in_atomic_block:
                    # Release savepoint if there is one
                    pass
                else:
                    # Commit transaction
                    try:
                        connection._commit()
                    except DatabaseError:
                        try:
                            connection._rollback()
                        except Error:
                            # An error during rollback means that something
                            # went wrong with the connection. Drop it.
                            connection.close()
                        raise
            else:
                # This flag will be set to True again if there isn't a savepoint
                # allowing to perform the rollback at this level.
                connection.needs_rollback = False
                if connection.in_atomic_block:
                    # Mark for rollback
                    connection.needs_rollback = True
                else:
                    # Roll back transaction
                    try:
                        connection.rollback()
                    except Error:
                        # An error during rollback means that something
                        # went wrong with the connection. Drop it.
                        connection.close()
        finally:
            # Outermost block exit when autocommit was enabled.
            if not connection.in_atomic_block:
                if connection.closed_in_transaction:
                    connection.connection = None
                else:
                    connection.set_autocommit(True)
            # Outermost block exit when autocommit was disabled.
            elif not connection.commit_on_exit:
                if connection.closed_in_transaction:
                    connection.connection = None
                else:
                    connection.in_atomic_block = False


def atomic(using=None, durable=False):
    # Bare decorator: @atomic -- although the first argument is called
    # `using`, it's actually the function being decorated.
    if callable(using):
        return Atomic(DEFAULT_DB_ALIAS, durable)(using)
    # Decorator: @atomic(...) or context manager: with atomic(...): ...
    return Atomic(using, durable)


def _non_atomic_requests(view, using):
    try:
        view._non_atomic_requests.add(using)
    except AttributeError:
        view._non_atomic_requests = {using}
    return view


def non_atomic_requests(using=None):
    if callable(using):
        return _non_atomic_requests(using, DEFAULT_DB_ALIAS)
    if using is None:
        using = DEFAULT_DB_ALIAS
    return lambda view: _non_atomic_requests(view, using)
