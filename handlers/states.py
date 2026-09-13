from aiogram.fsm.state import State, StatesGroup


class CreateMuscleGroup(StatesGroup):
    name = State()


class CreateExercise(StatesGroup):
    muscle_group = State()
    name = State()
    sets = State()
    target = State()
    load_unit = State()
    rest = State()
    description = State()
    media = State()


class EditExerciseValue(StatesGroup):
    value = State()


class EditExerciseContent(StatesGroup):
    description = State()
    media = State()


class CreateTrainingDay(StatesGroup):
    name = State()
    weekdays = State()
    reminder_time = State()
    groups = State()
    exercises = State()
    alternative_bases = State()
    alternatives = State()
