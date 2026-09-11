from aiogram.fsm.state import State, StatesGroup


class CreateMuscleGroup(StatesGroup):
    name = State()


class CreateExercise(StatesGroup):
    muscle_group = State()
    name = State()
    sets = State()
    target = State()
    rest = State()
    description = State()
    media = State()


class EditExerciseContent(StatesGroup):
    description = State()
    media = State()


class CreateTrainingDay(StatesGroup):
    name = State()
    weekdays = State()
    reminder_time = State()
    groups = State()
    group_count = State()
