from aiogram.fsm.state import State, StatesGroup

class SearchStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_phone_source = State()
    waiting_for_fns = State()
    waiting_for_plate = State()
    waiting_for_source = State()
    waiting_github_username = State() 
    waiting_github_compare_1 = State()
    waiting_github_compare_2 = State()
    searching = State()