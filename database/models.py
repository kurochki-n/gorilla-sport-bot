from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Float,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Samara")

    muscle_groups: Mapped[list["MuscleGroup"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exercises: Mapped[list["Exercise"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    training_days: Mapped[list["TrainingDay"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workout_sessions: Mapped[list["WorkoutSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class MuscleGroup(Base, TimestampMixin):
    __tablename__ = "muscle_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    user: Mapped[User] = relationship(back_populates="muscle_groups")
    exercises: Mapped[list["Exercise"]] = relationship(back_populates="muscle_group")
    training_day_links: Mapped[list["TrainingDayGroup"]] = relationship(
        back_populates="muscle_group"
    )


class Exercise(Base, TimestampMixin):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    muscle_group_id: Mapped[int] = mapped_column(
        ForeignKey("muscle_groups.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    default_sets: Mapped[int] = mapped_column(Integer, default=3)
    target_text: Mapped[str] = mapped_column(String(100), default="8–12 повторений")
    rest_seconds: Mapped[int] = mapped_column(Integer, default=90)
    load_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    user: Mapped[User] = relationship(back_populates="exercises")
    muscle_group: Mapped[MuscleGroup] = relationship(back_populates="exercises")
    training_day_links: Mapped[list["TrainingDayExercise"]] = relationship(
        back_populates="exercise"
    )


class TrainingDay(Base, TimestampMixin):
    __tablename__ = "training_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    weekdays_mask: Mapped[int] = mapped_column(Integer)
    reminder_time: Mapped[time] = mapped_column(Time, default=time(12, 0))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    inactive_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    user: Mapped[User] = relationship(back_populates="training_days")
    muscle_groups: Mapped[list["TrainingDayGroup"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
        order_by="TrainingDayGroup.position",
    )
    exercises: Mapped[list["TrainingDayExercise"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
        order_by="TrainingDayExercise.position",
    )
    sessions: Mapped[list["WorkoutSession"]] = relationship(
        back_populates="training_day"
    )

    def is_scheduled_for(self, day: date) -> bool:
        if self.inactive_from is not None and day >= self.inactive_from:
            return False
        return bool(self.weekdays_mask & (1 << day.weekday()))


class TrainingDayGroup(Base, TimestampMixin):
    __tablename__ = "training_day_groups"
    __table_args__ = (
        UniqueConstraint(
            "training_day_id", "muscle_group_id", name="uq_training_day_group"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    training_day_id: Mapped[int] = mapped_column(
        ForeignKey("training_days.id", ondelete="CASCADE"), index=True
    )
    muscle_group_id: Mapped[int] = mapped_column(
        ForeignKey("muscle_groups.id", ondelete="RESTRICT"), index=True
    )
    exercise_count: Mapped[int] = mapped_column(Integer, default=2)
    position: Mapped[int] = mapped_column(Integer, default=1)

    training_day: Mapped[TrainingDay] = relationship(back_populates="muscle_groups")
    muscle_group: Mapped[MuscleGroup] = relationship(
        back_populates="training_day_links"
    )


class TrainingDayExercise(Base, TimestampMixin):
    __tablename__ = "training_day_exercises"
    __table_args__ = (
        UniqueConstraint("training_day_id", "exercise_id", name="uq_training_day_exercise"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    training_day_id: Mapped[int] = mapped_column(
        ForeignKey("training_days.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1)

    training_day: Mapped[TrainingDay] = relationship(back_populates="exercises")
    exercise: Mapped[Exercise] = relationship(back_populates="training_day_links")
    alternatives: Mapped[list["TrainingDayExerciseAlternative"]] = relationship(
        back_populates="training_day_exercise",
        cascade="all, delete-orphan",
        order_by="TrainingDayExerciseAlternative.position",
    )


class TrainingDayExerciseAlternative(Base, TimestampMixin):
    __tablename__ = "training_day_exercise_alternatives"
    __table_args__ = (
        UniqueConstraint(
            "training_day_exercise_id", "exercise_id", name="uq_training_day_exercise_alternative"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    training_day_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("training_day_exercises.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1)

    training_day_exercise: Mapped[TrainingDayExercise] = relationship(
        back_populates="alternatives"
    )
    exercise: Mapped[Exercise] = relationship()


class WorkoutSession(Base, TimestampMixin):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        UniqueConstraint(
            "training_day_id", "scheduled_date", name="uq_workout_session"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    training_day_id: Mapped[int] = mapped_column(
        ForeignKey("training_days.id", ondelete="RESTRICT"), index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="workout_sessions")
    training_day: Mapped[TrainingDay] = relationship(back_populates="sessions")
    exercises: Mapped[list["WorkoutExercise"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.position",
    )

    @property
    def sets_total(self) -> int:
        return sum(item.sets_total for item in self.exercises)

    @property
    def sets_done(self) -> int:
        return sum(item.sets_done for item in self.exercises)

    @property
    def is_completed(self) -> bool:
        return bool(self.exercises) and self.sets_done >= self.sets_total


class WorkoutExercise(Base, TimestampMixin):
    __tablename__ = "workout_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    training_day_exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_day_exercises.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    muscle_group_id: Mapped[int] = mapped_column(
        ForeignKey("muscle_groups.id", ondelete="RESTRICT"), index=True
    )
    exercise_name: Mapped[str] = mapped_column(String(100))
    muscle_group_name: Mapped[str] = mapped_column(String(80))
    sets_total: Mapped[int] = mapped_column(Integer)
    sets_done: Mapped[int] = mapped_column(Integer, default=0)
    target_text: Mapped[str] = mapped_column(String(100))
    rest_seconds: Mapped[int] = mapped_column(Integer, default=90)
    load_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    position: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped[WorkoutSession] = relationship(back_populates="exercises")
    training_day_exercise: Mapped[TrainingDayExercise | None] = relationship()
    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout_exercise",
        cascade="all, delete-orphan",
        order_by="WorkoutSet.position",
    )

    @property
    def is_completed(self) -> bool:
        return self.sets_done >= self.sets_total


class WorkoutSet(Base, TimestampMixin):
    __tablename__ = "workout_sets"
    __table_args__ = (
        UniqueConstraint("workout_exercise_id", "position", name="uq_workout_set"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workout_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("workout_exercises.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    load_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    repetitions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    workout_exercise: Mapped[WorkoutExercise] = relationship(back_populates="sets")


class NotificationLog(Base, TimestampMixin):
    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint("session_id", "kind", name="uq_workout_notification"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
