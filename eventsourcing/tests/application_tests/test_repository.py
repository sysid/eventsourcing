from datetime import datetime
from decimal import Decimal
from functools import reduce
from unittest.case import TestCase
from uuid import uuid4

from eventsourcing.application import AggregateNotFound, Repository
from eventsourcing.domain import TZINFO, Aggregate, Snapshot
from eventsourcing.persistence import (
    DatetimeAsISO,
    DecimalAsStr,
    EventStore,
    JSONTranscoder,
    Mapper,
    UUIDAsHex,
)
from eventsourcing.popo import POPOAggregateRecorder
from eventsourcing.sqlite import SQLiteAggregateRecorder, SQLiteDatastore
from eventsourcing.tests.application_tests.test_application_with_popo import (
    EmailAddressAsStr,
)
from eventsourcing.tests.domain_tests.test_aggregate import BankAccount
from eventsourcing.utils import get_topic


class TestRepository(TestCase):
    def test_with_snapshot_store(self) -> None:
        transcoder = JSONTranscoder()
        transcoder.register(UUIDAsHex())
        transcoder.register(DecimalAsStr())
        transcoder.register(DatetimeAsISO())
        transcoder.register(EmailAddressAsStr())

        event_recorder = SQLiteAggregateRecorder(SQLiteDatastore(":memory:"))
        event_recorder.create_table()
        event_store = EventStore(
            mapper=Mapper(transcoder=transcoder),
            recorder=event_recorder,
        )
        snapshot_recorder = SQLiteAggregateRecorder(SQLiteDatastore(":memory:"))
        snapshot_recorder.create_table()
        snapshot_store = EventStore(
            mapper=Mapper(transcoder=transcoder),
            recorder=snapshot_recorder,
        )
        repository: Repository = Repository(event_store, snapshot_store)

        # Check key error.
        with self.assertRaises(AggregateNotFound):
            repository.get(uuid4())

        # Open an account.
        account = BankAccount.open(
            full_name="Alice",
            email_address="alice@example.com",
        )

        # Credit the account.
        account.append_transaction(Decimal("10.00"))
        account.append_transaction(Decimal("25.00"))
        account.append_transaction(Decimal("30.00"))

        # Collect pending events.
        pending = account.collect_events()

        # Store pending events.
        event_store.put(pending)

        copy = repository.get(account.id)
        assert isinstance(copy, BankAccount)
        # Check copy has correct attribute values.
        assert copy.id == account.id
        assert copy.balance == Decimal("65.00")

        snapshot = Snapshot(
            originator_id=account.id,
            originator_version=account.version,
            timestamp=datetime.now(tz=TZINFO),
            topic=get_topic(type(account)),
            state=account.__dict__,
        )
        snapshot_store.put([snapshot])

        copy2 = repository.get(account.id)
        assert isinstance(copy2, BankAccount)

        # Check copy has correct attribute values.
        assert copy2.id == account.id
        assert copy2.balance == Decimal("65.00")

        # Credit the account.
        account.append_transaction(Decimal("10.00"))
        event_store.put(account.collect_events())

        # Check copy has correct attribute values.
        copy3 = repository.get(account.id)
        assert isinstance(copy3, BankAccount)

        assert copy3.id == account.id
        assert copy3.balance == Decimal("75.00")

        # Check can get old version of account.
        copy4 = repository.get(account.id, version=copy.version)
        assert isinstance(copy4, BankAccount)
        assert copy4.balance == Decimal("65.00")

        copy5 = repository.get(account.id, version=1)
        assert isinstance(copy5, BankAccount)
        assert copy5.balance == Decimal("0.00")

        copy6 = repository.get(account.id, version=2)
        assert isinstance(copy6, BankAccount)
        assert copy6.balance == Decimal("10.00")

        copy7 = repository.get(account.id, version=3)
        assert isinstance(copy7, BankAccount)
        assert copy7.balance == Decimal("35.00"), copy7.balance

        copy8 = repository.get(account.id, version=4)
        assert isinstance(copy8, BankAccount)
        assert copy8.balance == Decimal("65.00"), copy8.balance

        # # Check the __getitem__ method is working
        # copy9 = repository[account.uuid]
        # self.assertEqual(copy9.balance, Decimal("75.00"))
        #
        # copy10 = repository[account.uuid, 3]
        # # assert isinstance(copy7, BankAccount)
        #
        # self.assertEqual(copy10.balance, Decimal("35.00"))

    def test_without_snapshot_store(self) -> None:
        transcoder = JSONTranscoder()
        transcoder.register(UUIDAsHex())
        transcoder.register(DecimalAsStr())
        transcoder.register(DatetimeAsISO())
        transcoder.register(EmailAddressAsStr())

        event_recorder = SQLiteAggregateRecorder(SQLiteDatastore(":memory:"))
        event_recorder.create_table()
        event_store = EventStore(
            mapper=Mapper(transcoder=transcoder),
            recorder=event_recorder,
        )
        repository: Repository = Repository(event_store)

        # Check key error.
        with self.assertRaises(AggregateNotFound):
            repository.get(uuid4())

        # Open an account.
        account = BankAccount.open(
            full_name="Alice",
            email_address="alice@example.com",
        )

        # Credit the account.
        account.append_transaction(Decimal("10.00"))
        account.append_transaction(Decimal("25.00"))
        account.append_transaction(Decimal("30.00"))

        # Collect pending events.
        pending = account.collect_events()

        # Store pending events.
        event_store.put(pending)

        copy = repository.get(account.id)
        assert isinstance(copy, BankAccount)
        # Check copy has correct attribute values.
        assert copy.id == account.id
        assert copy.balance == Decimal("65.00")

        # Credit the account.
        account.append_transaction(Decimal("10.00"))
        event_store.put(account.collect_events())

        # Check copy has correct attribute values.
        copy2 = repository.get(account.id)
        assert isinstance(copy2, BankAccount)

        assert copy2.id == account.id
        assert copy2.balance == Decimal("75.00")

        # Check can get old version of account.
        copy3 = repository.get(account.id, version=copy.version)
        assert isinstance(copy3, BankAccount)
        assert copy3.balance == Decimal("65.00")

        copy4 = repository.get(account.id, version=1)
        assert isinstance(copy4, BankAccount)
        assert copy4.balance == Decimal("0.00")

        copy5 = repository.get(account.id, version=2)
        assert isinstance(copy5, BankAccount)
        assert copy5.balance == Decimal("10.00")

        copy6 = repository.get(account.id, version=3)
        assert isinstance(copy6, BankAccount)
        assert copy6.balance == Decimal("35.00"), copy6.balance

        copy7 = repository.get(account.id, version=4)
        assert isinstance(copy7, BankAccount)
        assert copy7.balance == Decimal("65.00"), copy7.balance

    def test_with_alternative_mutator_function(self):
        def mutator(initial, domain_events):
            return reduce(lambda a, e: e.mutate(a), domain_events, initial)

        transcoder = JSONTranscoder()
        transcoder.register(UUIDAsHex())
        transcoder.register(DecimalAsStr())
        transcoder.register(DatetimeAsISO())
        transcoder.register(EmailAddressAsStr())

        event_recorder = SQLiteAggregateRecorder(SQLiteDatastore(":memory:"))
        event_recorder.create_table()
        event_store = EventStore(
            mapper=Mapper(transcoder=transcoder),
            recorder=event_recorder,
        )
        snapshot_recorder = SQLiteAggregateRecorder(SQLiteDatastore(":memory:"))
        snapshot_recorder.create_table()
        snapshot_store = EventStore(
            mapper=Mapper(transcoder=transcoder),
            recorder=snapshot_recorder,
        )
        repository: Repository = Repository(event_store, snapshot_store)

        # Check key error.
        with self.assertRaises(AggregateNotFound):
            repository.get(uuid4())

        # Open an account.
        account = BankAccount.open(
            full_name="Alice",
            email_address="alice@example.com",
        )

        # Credit the account.
        account.append_transaction(Decimal("10.00"))
        account.append_transaction(Decimal("25.00"))
        account.append_transaction(Decimal("30.00"))

        # Collect pending events.
        pending = account.collect_events()

        # Store pending events.
        event_store.put(pending)

        copy = repository.get(account.id, projector_func=mutator)
        assert isinstance(copy, BankAccount)
        # Check copy has correct attribute values.
        assert copy.id == account.id
        assert copy.balance == Decimal("65.00")

        snapshot = Snapshot(
            originator_id=account.id,
            originator_version=account.version,
            timestamp=datetime.now(tz=TZINFO),
            topic=get_topic(type(account)),
            state=account.__dict__,
        )
        snapshot_store.put([snapshot])

        copy2 = repository.get(account.id)
        assert isinstance(copy2, BankAccount)

        # Check copy has correct attribute values.
        assert copy2.id == account.id
        assert copy2.balance == Decimal("65.00")

        # Credit the account.
        account.append_transaction(Decimal("10.00"))
        event_store.put(account.collect_events())

        # Check copy has correct attribute values.
        copy3 = repository.get(account.id)
        assert isinstance(copy3, BankAccount)

        assert copy3.id == account.id
        assert copy3.balance == Decimal("75.00")

        # Check can get old version of account.
        copy4 = repository.get(account.id, version=copy.version)
        assert isinstance(copy4, BankAccount)
        assert copy4.balance == Decimal("65.00")

        copy5 = repository.get(account.id, version=1)
        assert isinstance(copy5, BankAccount)
        assert copy5.balance == Decimal("0.00")

        copy6 = repository.get(account.id, version=2)
        assert isinstance(copy6, BankAccount)
        assert copy6.balance == Decimal("10.00")

        copy7 = repository.get(account.id, version=3)
        assert isinstance(copy7, BankAccount)
        assert copy7.balance == Decimal("35.00"), copy7.balance

        copy8 = repository.get(account.id, version=4)
        assert isinstance(copy8, BankAccount)
        assert copy8.balance == Decimal("65.00"), copy8.balance

    def test_contains(self):
        transcoder = JSONTranscoder()
        transcoder.register(UUIDAsHex())
        transcoder.register(DecimalAsStr())
        transcoder.register(DatetimeAsISO())

        event_recorder = POPOAggregateRecorder()
        event_store = EventStore(
            mapper=Mapper(transcoder=transcoder),
            recorder=event_recorder,
        )

        aggregate = Aggregate()
        event_store.put(aggregate.collect_events())

        repository: Repository = Repository(event_store)
        self.assertTrue(aggregate.id in repository)
        self.assertFalse(uuid4() in repository)
