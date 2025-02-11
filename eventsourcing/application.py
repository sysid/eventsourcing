import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import chain
from threading import Event
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
    List,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
)
from uuid import UUID

from eventsourcing.domain import (
    Aggregate,
    AggregateEvent,
    DomainEvent,
    Snapshot,
    TAggregate,
)
from eventsourcing.persistence import (
    ApplicationRecorder,
    DatetimeAsISO,
    DecimalAsStr,
    EventStore,
    InfrastructureFactory,
    JSONTranscoder,
    Mapper,
    Notification,
    Recording,
    Tracking,
    Transcoder,
    UUIDAsHex,
)
from eventsourcing.utils import Environment, EnvType

T = TypeVar("T")
ProjectorFunctionType = Callable[[Optional[T], Iterable[DomainEvent[T]]], Optional[T]]


def mutate_aggregate(
    aggregate: Optional[T], domain_events: Iterable[DomainEvent[T]]
) -> Optional[T]:
    """
    Mutator function for aggregate projections, which works
    by successively calling the mutate() method of the given
    list of domain events.
    """
    for domain_event in domain_events:
        aggregate = domain_event.mutate(aggregate)
    return aggregate


class Repository(Generic[TAggregate]):
    """Reconstructs aggregates from events in an
    :class:`~eventsourcing.persistence.EventStore`,
    possibly using snapshot store to avoid replaying
    all events."""

    def __init__(
        self,
        event_store: EventStore[AggregateEvent[TAggregate]],
        snapshot_store: Optional[EventStore[Snapshot[TAggregate]]] = None,
    ):
        """
        Initialises repository with given event store (an
        :class:`~eventsourcing.persistence.EventStore` for aggregate
        :class:`~eventsourcing.domain.AggregateEvent` objects)
        and optionally a snapshot store (an
        :class:`~eventsourcing.persistence.EventStore` for aggregate
        :class:`~eventsourcing.domain.Snapshot` objects).
        """
        self.event_store = event_store
        self.snapshot_store = snapshot_store

    def get(
        self,
        aggregate_id: UUID,
        version: Optional[int] = None,
        projector_func: ProjectorFunctionType[TAggregate] = mutate_aggregate,
    ) -> TAggregate:
        """
        Returns an :class:`~eventsourcing.domain.Aggregate`
        for given ID, optionally at the given version.
        """
        gt: Optional[int] = None

        if self.snapshot_store is not None:
            # Try to get a snapshot.
            snapshots = list(
                self.snapshot_store.get(
                    originator_id=aggregate_id,
                    desc=True,
                    limit=1,
                    lte=version,
                )
            )
            if snapshots:
                gt = snapshots[0].originator_version
        else:
            snapshots = []

        # Get aggregate events.
        aggregate_events = self.event_store.get(
            originator_id=aggregate_id,
            gt=gt,
            lte=version,
        )

        # Reconstruct the aggregate from its events.
        initial: Optional[TAggregate] = None
        aggregate = projector_func(initial, chain(snapshots, aggregate_events))

        # Raise exception if "not found".
        if aggregate is None:
            raise AggregateNotFound((aggregate_id, version))
        else:
            # Return the aggregate.
            return aggregate

    def __contains__(self, item: UUID) -> bool:
        try:
            self.get(aggregate_id=item)
        except AggregateNotFound:
            return False
        else:
            return True


@dataclass(frozen=True)
class Section:
    # noinspection PyUnresolvedReferences
    """
    Frozen dataclass that represents a section from a :class:`NotificationLog`.
    The :data:`items` attribute contains a list of
    :class:`~eventsourcing.persistence.Notification` objects.
    The :data:`id` attribute is the section ID, two integers
    separated by a comma that described the first and last
    notification ID that are included in the section.
    The :data:`next_id` attribute describes the section ID
    of the next section, and will be set if the section contains
    as many notifications are were requested.

    Constructor arguments:

    :param Optional[str] id: section ID of this section e.g. "1,10"
    :param List[Notification] items: a list of event notifications
    :param Optional[str] next_id: section ID of the following section
    """

    id: Optional[str]
    items: List[Notification]
    next_id: Optional[str]


class NotificationLog(ABC):
    """
    Abstract base class for notification logs.
    """

    @abstractmethod
    def __getitem__(self, section_id: str) -> Section:
        """
        Returns a :class:`Section` of
        :class:`~eventsourcing.persistence.Notification` objects
        from the notification log.
        """

    @abstractmethod
    def select(
        self,
        start: int,
        limit: int,
        stop: Optional[int] = None,
        topics: Sequence[str] = (),
    ) -> List[Notification]:
        """
        Returns a selection
        :class:`~eventsourcing.persistence.Notification` objects
        from the notification log.
        """


class LocalNotificationLog(NotificationLog):
    """
    Notification log that presents sections of event notifications
    retrieved from an :class:`~eventsourcing.persistence.ApplicationRecorder`.
    """

    DEFAULT_SECTION_SIZE = 10

    def __init__(
        self,
        recorder: ApplicationRecorder,
        section_size: int = DEFAULT_SECTION_SIZE,
    ):
        """
        Initialises a local notification object with given
        :class:`~eventsourcing.persistence.ApplicationRecorder`
        and an optional section size.

        Constructor arguments:

        :param ApplicationRecorder recorder: application recorder from which event
            notifications will be selected
        :param int section_size: number of notifications to include in a section

        """
        self.recorder = recorder
        self.section_size = section_size

    def __getitem__(self, requested_section_id: str) -> Section:
        """
        Returns a :class:`Section` of event notifications
        based on the requested section ID. The section ID of
        the returned section will describe the event
        notifications that are actually contained in
        the returned section, and may vary from the
        requested section ID if there are less notifications
        in the recorder than were requested, or if there
        are gaps in the sequence of recorded event notification.
        """
        # Interpret the section ID.
        parts = requested_section_id.split(",")
        part1 = int(parts[0])
        part2 = int(parts[1])
        start = max(1, part1)
        limit = min(max(0, part2 - start + 1), self.section_size)

        # Select notifications.
        notifications = self.select(start, limit)

        # Get next section ID.
        actual_section_id: Optional[str]
        next_id: Optional[str]
        if len(notifications):
            last_notification_id = notifications[-1].id
            actual_section_id = self.format_section_id(
                notifications[0].id, last_notification_id
            )
            if len(notifications) == limit:
                next_id = self.format_section_id(
                    last_notification_id + 1, last_notification_id + limit
                )
            else:
                next_id = None
        else:
            actual_section_id = None
            next_id = None

        # Return a section of the notification log.
        return Section(
            id=actual_section_id,
            items=notifications,
            next_id=next_id,
        )

    def select(
        self,
        start: int,
        limit: int,
        stop: Optional[int] = None,
        topics: Sequence[str] = (),
    ) -> List[Notification]:
        """
        Returns a selection
        :class:`~eventsourcing.persistence.Notification` objects
        from the notification log.
        """
        if limit > self.section_size:
            raise ValueError(
                f"Requested limit {limit} greater than section size {self.section_size}"
            )
        return self.recorder.select_notifications(
            start=start, limit=limit, stop=stop, topics=topics
        )

    @staticmethod
    def format_section_id(first_id: int, last_id: int) -> str:
        return "{},{}".format(first_id, last_id)


class ProcessingEvent:
    """
    Keeps together a :class:`~eventsourcing.persistence.Tracking`
    object, which represents the position of a domain event notification
    in the notification log of a particular application, and the
    new domain events that result from processing that notification.
    """

    def __init__(self, tracking: Optional[Tracking] = None):
        """
        Initialises the process event with the given tracking object.
        """
        self.tracking = tracking
        self.events: List[AggregateEvent[Any]] = []
        self.aggregates: Dict[UUID, Aggregate] = {}
        self.saved_kwargs: Dict[Any, Any] = {}

    def collect_events(
        self,
        *objs: Optional[Union[Aggregate, AggregateEvent[Aggregate]]],
        **kwargs: Any,
    ) -> None:
        """
        Collects pending domain events from the given aggregate.
        """
        for obj in objs:
            if isinstance(obj, AggregateEvent):
                self.events.append(obj)
            elif isinstance(obj, Aggregate):
                self.aggregates[obj.id] = obj
                for event in obj.collect_events():
                    self.events.append(event)
        self.saved_kwargs.update(kwargs)

    def save(
        self,
        *aggregates: Optional[Union[Aggregate, AggregateEvent[Aggregate]]],
        **kwargs: Any,
    ) -> None:
        """
        DEPRECATED, in favour of collect_events(). Will be removed in future version.

        Collects pending domain events from the given aggregate.
        """
        self.collect_events(*aggregates, **kwargs)


class RecordingEvent:
    def __init__(
        self,
        application_name: str,
        recordings: List[Recording],
        previous_max_notification_id: Optional[int],
    ):
        self.application_name = application_name
        self.recordings = recordings
        self.previous_max_notification_id = previous_max_notification_id


class Application(ABC, Generic[TAggregate]):
    """
    Base class for event-sourced applications.
    """

    name = "Application"
    env: EnvType = {}
    is_snapshotting_enabled: bool = False
    snapshotting_intervals: Optional[Dict[Type[Aggregate], int]] = None
    log_section_size = 10
    notify_topics: Sequence[str] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        if "name" not in cls.__dict__:
            cls.name = cls.__name__

    def __init__(self, env: Optional[EnvType] = None) -> None:
        """
        Initialises an application with an
        :class:`~eventsourcing.persistence.InfrastructureFactory`,
        a :class:`~eventsourcing.persistence.Mapper`,
        an :class:`~eventsourcing.persistence.ApplicationRecorder`,
        an :class:`~eventsourcing.persistence.EventStore`,
        a :class:`~eventsourcing.application.Repository`, and
        a :class:`~eventsourcing.application.LocalNotificationLog`.
        """
        self.env = self.construct_env(self.name, env)
        self.factory = self.construct_factory(self.env)
        self.mapper = self.construct_mapper()
        self.recorder = self.construct_recorder()
        self.events = self.construct_event_store()
        self.snapshots = self.construct_snapshot_store()
        self.repository = self.construct_repository()
        self.log = self.construct_notification_log()
        self.closing = Event()
        self.previous_max_notification_id: Optional[
            int
        ] = self.recorder.max_notification_id()

    def construct_env(self, name: str, env: Optional[EnvType] = None) -> Environment:
        """
        Constructs environment from which application will be configured.
        """
        _env = dict(type(self).env)
        if type(self).is_snapshotting_enabled or type(self).snapshotting_intervals:
            _env["IS_SNAPSHOTTING_ENABLED"] = "y"
        _env.update(os.environ)
        if env is not None:
            _env.update(env)
        return Environment(name, _env)

    def construct_factory(self, env: Environment) -> InfrastructureFactory:
        """
        Constructs an :class:`~eventsourcing.persistence.InfrastructureFactory`
        for use by the application.
        """
        return InfrastructureFactory.construct(env)

    def construct_mapper(self) -> Mapper:
        """
        Constructs a :class:`~eventsourcing.persistence.Mapper`
        for use by the application.
        """
        return self.factory.mapper(
            transcoder=self.construct_transcoder(),
        )

    def construct_transcoder(self) -> Transcoder:
        """
        Constructs a :class:`~eventsourcing.persistence.Transcoder`
        for use by the application.
        """
        transcoder = JSONTranscoder()
        self.register_transcodings(transcoder)
        return transcoder

    # noinspection SpellCheckingInspection
    def register_transcodings(self, transcoder: Transcoder) -> None:
        """
        Registers :class:`~eventsourcing.persistence.Transcoding`
        objects on given :class:`~eventsourcing.persistence.JSONTranscoder`.
        """
        transcoder.register(UUIDAsHex())
        transcoder.register(DecimalAsStr())
        transcoder.register(DatetimeAsISO())

    def construct_recorder(self) -> ApplicationRecorder:
        """
        Constructs an :class:`~eventsourcing.persistence.ApplicationRecorder`
        for use by the application.
        """
        return self.factory.application_recorder()

    def construct_event_store(self) -> EventStore[AggregateEvent[TAggregate]]:
        """
        Constructs an :class:`~eventsourcing.persistence.EventStore`
        for use by the application to store and retrieve aggregate
        :class:`~eventsourcing.domain.AggregateEvent` objects.
        """
        return self.factory.event_store(
            mapper=self.mapper,
            recorder=self.recorder,
        )

    def construct_snapshot_store(self) -> Optional[EventStore[Snapshot[TAggregate]]]:
        """
        Constructs an :class:`~eventsourcing.persistence.EventStore`
        for use by the application to store and retrieve aggregate
        :class:`~eventsourcing.domain.Snapshot` objects.
        """
        if not self.factory.is_snapshotting_enabled():
            return None
        recorder = self.factory.aggregate_recorder(purpose="snapshots")
        return self.factory.event_store(
            mapper=self.mapper,
            recorder=recorder,
        )

    def construct_repository(self) -> Repository[TAggregate]:
        """
        Constructs a :class:`Repository` for use by the application.
        """
        return Repository(
            event_store=self.events,
            snapshot_store=self.snapshots,
        )

    def construct_notification_log(self) -> LocalNotificationLog:
        """
        Constructs a :class:`LocalNotificationLog` for use by the application.
        """
        return LocalNotificationLog(self.recorder, section_size=self.log_section_size)

    def save(
        self,
        *objs: Optional[Union[TAggregate, AggregateEvent[Aggregate]]],
        **kwargs: Any,
    ) -> List[Recording]:
        """
        Collects pending events from given aggregates and
        puts them in the application's event store.
        """
        processing_event = ProcessingEvent()
        processing_event.collect_events(*objs, **kwargs)
        recordings = self._record(processing_event)
        self._take_snapshots(processing_event)
        self._notify(recordings)
        self.notify(processing_event.events)  # Deprecated.
        return recordings

    def _record(self, processing_event: ProcessingEvent) -> List[Recording]:
        """
        Records given process event in the application's recorder.
        """
        return self.events.put(
            processing_event.events,
            tracking=processing_event.tracking,
            **processing_event.saved_kwargs,
        )

    def _take_snapshots(self, processing_event: ProcessingEvent) -> None:
        # Take snapshots using IDs and types.
        if self.snapshots and self.snapshotting_intervals:
            for event in processing_event.events:
                try:
                    aggregate = processing_event.aggregates[event.originator_id]
                except KeyError:
                    continue
                interval = self.snapshotting_intervals.get(type(aggregate))
                if interval is not None:
                    if event.originator_version % interval == 0:
                        self.take_snapshot(
                            aggregate_id=event.originator_id,
                            version=event.originator_version,
                        )

    def take_snapshot(self, aggregate_id: UUID, version: Optional[int] = None) -> None:
        """
        Takes a snapshot of the recorded state of the aggregate,
        and puts the snapshot in the snapshot store.
        """
        if self.snapshots is None:
            raise AssertionError(
                "Can't take snapshot without snapshots store. Please "
                "set environment variable IS_SNAPSHOTTING_ENABLED to "
                "a true value (e.g. 'y'), or set 'is_snapshotting_enabled' "
                "on application class, or set 'snapshotting_intervals' on "
                "application class."
            )
        else:
            aggregate = self.repository.get(aggregate_id, version)
            snapshot = Snapshot.take(aggregate)
            self.snapshots.put([snapshot])

    def notify(self, new_events: List[AggregateEvent[Aggregate]]) -> None:
        """
        Deprecated.

        Called after new aggregate events have been saved. This
        method on this class doesn't actually do anything,
        but this method may be implemented by subclasses that
        need to take action when new domain events have been saved.
        """

    def _notify(self, recordings: List[Recording]) -> None:
        """
        Called after new aggregate events have been saved. This
        method on this class doesn't actually do anything,
        but this method may be implemented by subclasses that
        need to take action when new domain events have been saved.
        """

    def close(self) -> None:
        self.closing.set()
        self.factory.close()


TApplication = TypeVar("TApplication", bound=Application[Aggregate])


class AggregateNotFound(Exception):
    """
    Raised when an :class:`~eventsourcing.domain.Aggregate`
    object is not found in a :class:`Repository`.
    """
