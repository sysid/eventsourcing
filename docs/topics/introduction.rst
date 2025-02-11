============
Introduction
============

What is an event?
=================

The term 'event' is often used in discussions about event sourcing
as an abbreviation which refers to a specific kind of event. That is to say,
it refers to an individual atomic immutable decision originated by the domain
model of a software application, an occasion of experience that results in a
"stubborn fact".

Of course, as everybody knows, the commonsensical notion "event"
has a broader meaning.
Firstly, the commonsensical meaning includes all other such atomic "actual occasions"
of experience that result in all the other stubborn facts that
together make up the past. Such things importantly do not change. They are what they are.
But the commonsensical meaning includes also inter-related sets of such things,
"societies" of actual occasions, things that do indeed experience adventures of change.
For example, the ordinary physical and social objects that we encounter in daily life that are
each built up from an on-going history of inter-related decisions. A software system
is also an event, in this broader sense, and a developer is also an event. And so is
her cat and her cup of tea.

As Gilles Deleuze wrote in his book on Leibniz when discussing Alfred North Whitehead's
modern process philosophy:

.. pull-quote::

    *"A concert is being performed tonight. It is the event.
    Vibrations of sound disperse, periodic movements go
    through space with their harmonics or submultiples.
    The sounds have inner qualities of height, intensity,
    and timbre. The sources of the sounds, instrumental
    or vocal are not content only to send the sounds out:
    each one perceives its own, and perceives the others
    whilst perceiving its own. These are active perceptions
    that are expressed among each other, or else prehensions
    that are prehending one another: 'First the solitary piano
    grieved, like a bird abandoned by its mate; the violin
    heard its wail and responded to it like a neighbouring
    tree. It was like the beginning of the world. ...'"*


What is event sourcing?
=======================

One definition of event sourcing suggests the state of an
event-sourced application is determined by a sequence of events.
Another definition has event sourcing as a persistence mechanism
for domain-driven design.

Whilst the basic event sourcing patterns are quite simple and
can be reproduced in code for each project, event sourcing as a
persistence mechanism for domain-driven design appears as a
"conceptually cohesive mechanism" and so can be partitioned into
a "separate lightweight framework".

Quoting from Eric Evans' book `Domain-Driven Design
<https://en.wikipedia.org/wiki/Domain-driven_design>`__:

.. pull-quote::

    *"Partition a conceptually COHESIVE MECHANISM into a separate
    lightweight framework. Particularly watch for formalisms for
    well-documented categories of algorithms. Expose the capabilities of the
    framework with an INTENTION-REVEALING INTERFACE. Now the other elements
    of the domain can focus on expressing the problem ('what'), delegating
    the intricacies of the solution ('how') to the framework."*


This library
============

This is a library for event sourcing in Python. At its core, this library
supports storing and retrieving sequences of events, such as the domain events
of event-sourced aggregates in a domain-driven design, and snapshots of those
aggregates. A variety of schemas and technologies can be used for storing events,
and this library supports several of these possibilities.

To demonstrate how storing and retrieving domain events can be used effectively
as a persistence mechanism in an event-sourced application, this library includes
base classes and examples of event-sourced aggregates and event-sourced applications.

It is possible using this library to define an entire event-driven system of
event-sourced applications independently of infrastructure and mode of running.
That means system behaviours can be rapidly developed whilst running the entire
system synchronously in a single thread with a single in-memory database. And
then the system can be run asynchronously on a cluster with durable databases,
with the system effecting exactly the same behaviour.


Synopsis
========

Use the library's ``Aggregate`` base class to define event-sourced aggregates.
Use the ``@event`` decorator on command methods to define aggregate events.

.. code-block:: python

    from eventsourcing.domain import Aggregate, event

    class World(Aggregate):
        @event('Created')
        def __init__(self, name):
            self.name = name
            self.history = []

        @event('SomethingHappened')
        def make_it_so(self, what):
            self.history.append(what)


Use the library's ``Application`` class to define an event-sourced application.
Add command and query methods that use event-sourced aggregates.

.. code-block:: python

    from eventsourcing.application import Application

    class Universe(Application):
        def create_world(self, name):
            world = World(name)
            self.save(world)
            return world.id

        def make_it_so(self, world_id, what):
            world = self.repository.get(world_id)
            world.make_it_so(what)
            self.save(world)

        def get_history(self, world_id):
            world = self.repository.get(world_id)
            return world.history



Construct an application object by calling the application class.

.. code-block:: python

    application = Universe()


Evolve the state of the application by calling the
application command methods.

.. code-block:: python

    world_id = application.create_world('Earth')
    application.make_it_so(world_id, 'dinosaurs')
    application.make_it_so(world_id, 'trucks')
    application.make_it_so(world_id, 'internet')


Access the state of the application by calling the
application query methods.

.. code-block:: python

    history = application.get_history(world_id)
    assert history == ['dinosaurs', 'trucks', 'internet']


Configure an application by setting environment variables.

.. code-block:: python

    application = Universe(
        env={
            'PERSISTENCE_MODULE': 'eventsourcing.sqlite',
            'SQLITE_DBNAME': ':memory:',
        }
    )

Please follow the :doc:`Tutorial </topics/tutorial>` for more information.

Features
========

**Flexible event store** — flexible persistence of domain events. Combines
an event mapper and an event recorder in ways that can be easily extended.
Mapper uses a transcoder that can be easily extended to support custom
model object types. Recorders supporting different databases can be easily
substituted and configured with environment variables.

**Domain models and applications** — base classes for domain model aggregates
and applications. Suggests how to structure an event-sourced application.

**Application-level encryption and compression** — encrypts and decrypts events inside the
application. This means data will be encrypted in transit across a network ("on the wire")
and at disk level including backups ("at rest"), which is a legal requirement in some
jurisdictions when dealing with personally identifiable information (PII) for example
the EU's GDPR. Compression reduces the size of stored domain events and snapshots, usually
by around 25% to 50% of the original size. Compression reduces the size of data
in the database and decreases transit time across a network.

**Snapshotting** — reduces access-time for aggregates with many domain events.

**Versioning** - allows domain model changes to be introduced after an application
has been deployed. Both domain events and aggregate classes can be versioned.
The recorded state of an older version can be upcast to be compatible with a new
version. Stored events and snapshots are upcast from older versions
to new versions before the event or aggregate object is reconstructed.

**Optimistic concurrency control** — ensures a distributed or horizontally scaled
application doesn't become inconsistent due to concurrent method execution. Leverages
optimistic concurrency controls in adapted database management systems.

**Notifications and projections** — reliable propagation of application
events with pull-based notifications allows the application state to be
projected accurately into replicas, indexes, view models, and other applications.
Supports materialized views and CQRS.

**Event-driven systems** — reliable event processing. Event-driven systems
can be defined independently of particular persistence infrastructure and mode of
running.

**Detailed documentation** — documentation provides general overview, introduction
of concepts, explanation of usage, and detailed descriptions of library classes.
All code is annotated with type hints.

**Worked examples** — includes examples showing how to develop aggregates, applications
and systems.


..
    **Hash chaining** — Sequences of events can be hash-chained, and the entire sequence
    of events checked for data integrity. Information lost in transit or on the disk from
    database corruption can be detected. If the last hash can be independently validated,
    then so can the entire sequence.

..
    **Correlation and causation IDs** - Domain events can easily be given correlation and
    causation IDs, which allows a story to be traced through a system of applications.


Design overview
===============

The design of the library follows the notion of a "layered architecture" in
that there are distinct and separate layers for interfaces, application, domain,
and infrastructure. It also follows the "onion" or "hexagonal" or "clean"
architecture, in that the `domain layer <domain.html>`_ has no dependencies
on any other layer. The `application layer <application.html>`_ depends on
the domain and `infrastructure layers <persistence.html>`_, and the interface
layer depends only on the application layer.


Register issues
===============

This project is `hosted on GitHub <https://github.com/pyeventsourcing/eventsourcing>`__.
Please `register any issues, questions, and requests
<https://github.com/pyeventsourcing/eventsourcing/issues>`__ you may have.
