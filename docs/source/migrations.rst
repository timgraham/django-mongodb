Migrations API reference
========================

.. module:: django_mongodb.migrations

You can use PyMongo operations in your migrations. In lieu of Django's built-in
``RunSQL`` operation, use ``RunMQL``.

``RunMQL``
----------

.. class:: RunMQL(code, reverse_code=None, state_operations=None, hints=None, elidable=False)

Allows running of arbitrary MQL on the database - useful for more advanced
features of database backends that Django doesn't support directly.

``sql``, and ``reverse_sql`` if provided, should be strings of MQL to run on
the database.

The ``reverse_sql`` queries are executed when the migration is unapplied. They
should undo what is done by the ``sql`` queries. For example, to undo the above
insertion with a deletion::

    migrations.RunMQL(
        forward_func=[("INSERT INTO musician (name) VALUES (%s);", ["Reinhardt"])],
        reverse_func=[("DELETE FROM musician where name=%s;", ["Reinhardt"])],
    )

If ``reverse_sql`` is ``None`` (the default), the ``RunMQL`` operation is
irreversible.

The ``state_operations`` argument allows you to supply operations that are
equivalent to the MQL in terms of project state. For example, if you are
manually creating a column, you should pass in a list containing an ``AddField``
operation here so that the autodetector still has an up-to-date state of the
model. If you don't, when you next run ``makemigrations``, it won't see any
operation that adds that field and so will try to run it again. For example::

    migrations.RunMQL(
        "ALTER TABLE musician ADD COLUMN name varchar(255) NOT NULL;",
        state_operations=[
            migrations.AddField(
                "musician",
                "name",
                models.CharField(max_length=255),
            ),
        ],
    )

The optional ``hints`` argument will be passed as ``**hints`` to the
:meth:`allow_migrate` method of database routers to assist them in making
routing decisions. See :ref:`topics-db-multi-db-hints` for more details on
database hints.

The optional ``elidable`` argument determines whether or not the operation will
be removed (elided) when :ref:`squashing migrations <migration-squashing>`.

.. attribute:: RunMQL.noop

    Pass the ``RunMQL.noop`` attribute to ``sql`` or ``reverse_sql`` when you
    want the operation not to do anything in the given direction. This is
    especially useful in making the operation reversible.


def forwards_func(apps, schema_editor, database):
