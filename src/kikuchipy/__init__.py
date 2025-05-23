#
# Copyright 2019-2025 the kikuchipy developers
#
# This file is part of kikuchipy.
#
# kikuchipy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# kikuchipy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with kikuchipy. If not, see <http://www.gnu.org/licenses/>.
#

import lazy_loader

# Initial committer first, then sorted by line contributions
credits = [
    "Håkon Wiik Ånes",
    "Lars Andreas Hastad Lervik",
    "Ole Natlandsmyr",
    "Thomas G. Woodcock",
    "Tina Bergh",
    "Eric Prestat",
    "Andreas V. Bugten",
    "Erlend Mikkelsen Østvold",
    "Zhou Xu",
    "Carter Francis",
    "Magnus Nord",
    "Tijmen Vermeij",
]
__version__ = "0.12.dev2"

__getattr__, __dir__, __all__ = lazy_loader.attach_stub(__name__, __file__)

del lazy_loader
