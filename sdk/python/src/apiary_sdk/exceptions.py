from superpos_sdk.exceptions import *  # noqa: F401,F403
from superpos_sdk.exceptions import PermissionError as SuperposPermissionError  # noqa: F401,A004
from superpos_sdk.exceptions import SuperposError

# Legacy class-name aliases so ``from apiary_sdk.exceptions import ApiaryError`` etc. work.
ApiaryError = SuperposError
ApiaryPermissionError = SuperposPermissionError
