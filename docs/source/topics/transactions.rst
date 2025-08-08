============
Transactions
============

.. versionadded:: 5.2.0b2

.. module:: django_mongodb_backend.transaction

MongoDB supports :doc:`transactions <manual:core/transactions>` if it's configured as a
:doc:`replica set <manual:replication>` or a :doc:`sharded cluster <manual:sharding>`.

Because MongoDB transactions have some limitations and are not meant to be used as
freely as SQL transactions, :doc:`Django's transactions APIs
<django:topics/db/transactions>`, including most notably
:func:`django.db.transaction.atomic`, function as no-ops.

Instead, Django MongoDB Backend provides its own
:func:`django_mongodb_backend.transaction.atomic` function.

Outside of a transaction, query execution uses Django and MongoDB's default behavior of
autocommit mode. Each query is immediately committed to the database.

Controlling transactions
========================

.. function:: atomic(using=None)

    Atomicity is the defining property of database transactions. ``atomic`` allows
    creating a block of code within which the atomicity on the database is guaranteed.
    If the block of code is successfully completed, the changes are committed to the
    database. If there is an exception, the changes are rolled back.

    On databases that support savepoints, ``atomic`` blocks can be nested, such that
    the outermost ``atomic`` starts a transaction and inner ``atomic``\s create
    savepoints. Since MongoDB doesn't support savepoints, inner ``atomic`` blocks
    don't have any effect. The transaction commits once the outermost ``atomic`` exits.

    ``atomic`` is usable both as a :py:term:`decorator`::

        from django_mongodb_backend import transaction


        @atomic
        def viewfunc(request):
            # This code executes inside a transaction.
            do_stuff()

    and as a :py:term:`context manager`::

        from django_mongodb_backend import transaction


        def viewfunc(request):
            # This code executes in autocommit mode (Django's default).
            do_stuff()

            with atomic():
                # This code executes inside a transaction.
                do_more_stuff()

    .. admonition:: Avoid catching exceptions inside ``atomic``!

        When exiting an ``atomic`` block, Django looks at whether it's exited normally
        or with an exception to determine whether to commit or roll back. If you catch
        and handle exceptions inside an ``atomic`` block, you may hide from Django the
        fact that a problem has happened. This can result in unexpected behavior.

        This is mostly a concern for :exc:`~django.db.DatabaseError` and its subclasses
        such as :exc:`~django.db.IntegrityError`. After such an error, the transaction
        is broken and Django will perform a rollback at the end of the ``atomic``
        block.

    .. admonition:: You may need to manually revert app state when rolling back a transaction.

        The values of a model's fields won't be reverted when a transaction rollback
        happens. This could lead to an inconsistent model state unless you manually
        restore the original field values.

        For example, given ``MyModel`` with an ``active`` field, this snippet ensures
        that the ``if obj.active`` check at the end uses the correct value if updating
        ``active`` to ``True`` fails in the transaction::

            from django_mongodb_backend import transaction
            from django.db import DatabaseError

            obj = MyModel(active=False)
            obj.active = True
            try:
                with transaction.atomic():
                    obj.save()
            except DatabaseError:
                obj.active = False

            if obj.active:
                ...

        This also applies to any other mechanism that may hold app state, such as
        caching or global variables. For example, if the code proactively updates data
        in the cache after saving an object, it's recommended to use
        :ref:`transaction.on_commit() <performing-actions-after-commit>` instead, to
        defer cache alterations until the transaction is actually committed.

    ``atomic`` takes a ``using`` argument which should be the name of a
    database. If this argument isn't provided, Django uses the ``"default"``
    database.

    Under the hood, Django's transaction management code:

    - opens a transaction when entering the outermost ``atomic`` block
    - commits or rolls back the transaction when exiting the outermost block.

.. admonition:: Performance considerations

    Open transactions have a performance cost for your database server. To minimize
    this overhead, keep your transactions as short as possible. This is especially
    important if you're using :func:`atomic` in long-running processes, outside of
    Django's request / response cycle.

Performing actions after commit
===============================

The :func:`atomic` function supports Django's :func:`~django.db.transaction.on_commit`
API to :ref:`perform actions after a transaction successfully commits
<performing-actions-after-commit>`.

.. _transactions-limitations:

Limitations
===========

MongoDB's transaction limitations that are applicable to Django are:

- :meth:`QuerySet.union() <django.db.models.query.QuerySet.union>` is not
  supported inside a transaction.
- If a transaction raises an exception, the transaction is no longer usable.
  For example, if the update stage of :meth:`QuerySet.update_or_create()
  <django.db.models.query.QuerySet.update_or_create>` fails with
  :class:`~django.db.IntegrityError` due to a unique constraint violation, the
  create stage won't be able to proceed.
  :class:`pymongo.errors.OperationFailure` is raised, wrapped by
  :class:`django.db.DatabaseError`.
- Savepoints (i.e. nested :func:`~django.db.transaction.atomic` blocks) aren't
  supported. The outermost :func:`~django.db.transaction.atomic` will start
  a transaction while any subsequent :func:`~django.db.transaction.atomic`
  blocks will have no effect.
- Migration operations aren't :ref:`wrapped in a transaction
  <topics/migrations:transactions>` because of MongoDB restrictions such as
  adding indexes to existing collections while in a transaction.
