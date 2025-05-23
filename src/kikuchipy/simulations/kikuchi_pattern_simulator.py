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

# The following copyright notice is included because a part of the
# calculation of kinematical master patterns in the stereographic
# projection in this file is derived from a similar routine in EMsoft
# (specifically, the selection of which unit vectors that are within a
# Kikuchi band):

# #####################################################################
# Copyright (c) 2013-2022, Marc De Graef Research Group/Carnegie Mellon
# University
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#  - Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  - Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the
#    distribution.
#  - Neither the names of Marc De Graef, Carnegie Mellon University nor
#    the names of its contributors may be used to endorse or promote
#    products derived from this software without specific prior written
#    permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# ######################################################################

import sys
from typing import TYPE_CHECKING, Literal

import dask.array as da
from dask.diagnostics import ProgressBar
from diffsims.crystallography import ReciprocalLatticeVector
import matplotlib.colors as mcolors
import matplotlib.figure as mfigure
import matplotlib.pyplot as plt
import numba as nb
import numpy as np
from orix import projections
from orix.crystal_map import Phase
from orix.plot._util import Arrow3D
from orix.quaternion import Rotation
from orix.vector import Vector3d
from tqdm import tqdm

from kikuchipy._utils.numba import vec_dot
from kikuchipy._utils.vector import ValidHemispheres, poles_from_hemisphere
from kikuchipy.constants import dependency_version
from kikuchipy.detectors.ebsd_detector import EBSDDetector
from kikuchipy.signals.ebsd_master_pattern import EBSDMasterPattern
from kikuchipy.simulations._kikuchi_pattern_features import (
    KikuchiPatternLine,
    KikuchiPatternZoneAxis,
)
from kikuchipy.simulations._kikuchi_pattern_simulation import (
    GeometricalKikuchiPatternSimulation,
)

if TYPE_CHECKING:  # pragma: no cover
    from pyvista import Plotter


class KikuchiPatternSimulator:
    """Setup and calculation of geometrical or kinematical Kikuchi
    pattern simulations.

    Parameters
    ----------
    reflectors
        Reflectors to use in the simulation, flattened to one navigation
        dimension.
    """

    def __init__(self, reflectors: ReciprocalLatticeVector) -> None:
        self._reflectors = reflectors.deepcopy().flatten()

    @property
    def reflectors(self) -> ReciprocalLatticeVector:
        """Return the reflectors to use in the simulation."""
        return self._reflectors

    @property
    def phase(self) -> Phase:
        """Return the phase with unit cell and symmetry."""
        return self._reflectors.phase

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}:\n" + repr(self.reflectors)

    def calculate_master_pattern(
        self,
        half_size: int = 500,
        hemisphere: ValidHemispheres = "upper",
        scaling: Literal["linear", "square"] | None = "linear",
    ) -> EBSDMasterPattern:
        r"""Return a kinematical master pattern in the stereographic
        projection.

        Requires that :attr:`reflectors` have structure factors
        (:attr:`~diffsims.crystallography.ReciprocalLatticeVector.structure_factor`)
        and Bragg angles
        (:attr:`~diffsims.crystallography.ReciprocalLatticeVector.theta`)
        calculated.

        Parameters
        ----------
        half_size
            Number of pixels along the x-direction of the square master
            pattern. Default is 500. The full size will be 2 * half_size
            + 1, given a master pattern of shape (1001, 1001) for the
            default value.
        hemisphere
            Which hemisphere(s) to calculate. Options are "upper"
            (default), "lower", or "both".
        scaling
            Intensity scaling of the band kinematical intensities,
            either "linear" (default), :math:`|F|`, "square",
            :math:`|F|^2`, or None, giving all bands an intensity of 1.

        Returns
        -------
        master_pattern
            Kinematical master pattern in the stereographic projection.

        Notes
        -----
        The algorithm for selecting which unit vector is within a
        Kikuchi band is derived from a similar routine in EMsoft.
        """
        self._raise_if_no_theta()
        self._raise_if_no_structure_factor()

        size = int(2 * half_size + 1)

        poles = poles_from_hemisphere(hemisphere)

        match scaling:
            case "linear":
                intensity = abs(self.reflectors.structure_factor)
            case "square":
                factor = self.reflectors.structure_factor
                intensity = abs(factor * factor.conjugate())
            case None:
                intensity = np.ones(self.reflectors.size)
            case _:
                raise ValueError(
                    f"Unknown scaling {scaling!r}, options are 'linear', 'square', or "
                    "None"
                )

        xyz_reflector = Vector3d(self.reflectors).unit.data
        theta_reflector = self.reflectors.theta
        arr = np.linspace(-1, 1, size)
        X, Y = np.meshgrid(arr, arr)
        X = X.ravel()
        Y = Y.ravel()
        n_poles = len(poles)
        patterns = np.empty((n_poles, size * size), dtype=np.float64)

        for i in tqdm(range(n_poles), ncols=80):
            stereo2sphere = projections.InverseStereographicProjection(poles[i])
            v_hemi = stereo2sphere.xy2vector(X.ravel(), Y.ravel())
            xyz_hemi = v_hemi.data
            patterns[i] = get_pattern(
                intensity, xyz_hemi, xyz_reflector, theta_reflector
            )
        patterns = patterns.reshape(-1, size, size).squeeze()

        if hemisphere == "both":
            axes = [{"size": 2, "name": "hemisphere"}]
        else:
            axes = []
        for i, name in zip(range(2), ["height", "width"]):
            axis = {"size": size, "name": name, "offset": -size // 2, "units": "px"}
            axes.append(axis)

        return EBSDMasterPattern(
            patterns,
            axes=axes,
            phase=self.phase,
            hemisphere=hemisphere,
            projection="stereographic",
        )

    def on_detector(
        self, detector: EBSDDetector, rotations: Rotation
    ) -> GeometricalKikuchiPatternSimulation:
        """Project Kikuchi lines and zone axes onto a detector, one per
        crystal orientation.

        Parameters
        ----------
        detector
            EBSD detector describing the detector's view of the sample.
            If
            :attr:`~kikuchipy.detectors.EBSDDetector.navigation_shape`
            is anything else than ``(1,)``, it must be equal to the
            shape of the input ``rotations``.
        rotations
            Crystal orientations assumed to be expressed with respect to
            the default EDAX TSL sample reference frame RD-TD-ND in the
            Bunge convention. Rotation shape can be 1D or 2D.

        Returns
        -------
        simulations
            Geometrical Kikuchi pattern simulation.

        Notes
        -----
        This function is not optimized for large datasets, so use with
        care.
        """
        if (
            detector.navigation_shape != (1,)
            and detector.navigation_shape != rotations.shape
        ):
            raise ValueError(
                "`detector.navigation_shape` is not (1,) or equal to `rotations.shape`"
            )

        lattice = self.phase.structure.lattice
        ref = self._reflectors
        hkl = ref.hkl

        # Transformation from detector reference frame CSd to sample
        # reference frame CSs
        u_sample = Rotation.from_euler([0, detector.sample_tilt, 0], degrees=True)
        u_d = Rotation.from_euler(detector.euler, degrees=True)
        u_d_g = u_d.to_matrix().squeeze()
        u_detector = Rotation.from_matrix(u_d_g.T)
        u_s_bruker = u_sample * u_detector
        u_s_rot = Rotation.from_axes_angles((0, 0, -1), -np.pi / 2) * u_s_bruker
        u_s = da.from_array(u_s_rot.to_matrix().squeeze())

        # Transformation from CSs to cartesian crystal reference frame
        # CSc
        u_o = da.from_array(rotations.to_matrix())
        u_os = da.matmul(u_o, u_s)

        # Transformation from CSc to reciprocal crystal reference frame
        # CSk*
        u_astar = da.from_array(lattice.recbase.T)

        # Combine transformations
        u_kstar = da.matmul(u_astar, u_os)

        # Transform {hkl} from CSk* to CSd
        hkl_d = da.matmul(da.from_array(hkl), u_kstar)

        nav_axes = (0, 1)[: rotations.ndim]

        # Find bands that are in some pattern
        hkl_is_upper = da.greater(da.atleast_2d(hkl_d[..., 2]), 0)
        hkl_in_a_pattern = ~da.isclose(da.sum(hkl_is_upper, axis=nav_axes), 0)
        hkl_in_pattern = hkl_is_upper[..., hkl_in_a_pattern]
        hkl_d = hkl_d[..., hkl_in_a_pattern, :]
        with ProgressBar():
            print("Finding bands that are in some pattern:", file=sys.stdout)
            hkl_in_a_pattern = hkl_in_a_pattern.compute()

        # Visible reflectors
        visible_reflectors = self._reflectors[hkl_in_a_pattern]
        ref2 = ref[hkl_in_a_pattern]

        # Zone axes <uvw> from {hkl}
        ref2 = ref2.reshape(ref2.size, 1)
        uvw_miller = ref2.cross(ref2.transpose())

        # Remove [000] and reduce an index triplet to smallest integers
        uvw_miller = uvw_miller[~np.isclose(uvw_miller.data, 0).all(axis=-1)]
        uvw_miller = uvw_miller.round()
        uvw_miller = uvw_miller.unique()

        # Transformation from CSc to direct crystal reference frame CSk
        u_a = da.from_array(lattice.base)

        # Combine transformations
        u_k = da.matmul(u_a, u_os)

        # Transform direct lattice vectors from CSk to CSd
        uvw_d = da.matmul(da.from_array(uvw_miller.uvw), u_k)

        # Find zone axes that are in some pattern
        uvw_is_upper = da.greater(da.atleast_2d(uvw_d[..., 2]), 0)
        uvw_in_a_pattern = ~da.isclose(da.sum(uvw_is_upper, axis=nav_axes), 0)

        # Exclude those outside gnomonic bounds
        uvw_xg = uvw_d[..., 0] / uvw_d[..., 2]
        uvw_yg = uvw_d[..., 1] / uvw_d[..., 2]
        # Get gnomonic bounds
        x_range = detector.x_range
        y_range = detector.y_range
        # Extend gnomonic bounds by one detector pixel to include zone
        # axes on the detector border
        x_scale = detector.x_scale
        y_scale = detector.y_scale
        x_range[..., 0] -= x_scale
        x_range[..., 1] += x_scale
        y_range[..., 0] -= y_scale
        y_range[..., 1] += y_scale
        # Add an extra dimension to account for n number of zone axes in
        # the last dimension for the gnomonic coordinate arrays
        x_range = np.expand_dims(x_range, axis=-2)
        y_range = np.expand_dims(y_range, axis=-2)
        # Get boolean array
        within_x = da.logical_and(uvw_xg >= x_range[..., 0], uvw_xg <= x_range[..., 1])
        within_y = da.logical_and(uvw_yg >= y_range[..., 0], uvw_yg <= y_range[..., 1])
        within_gnomonic_bounds = da.any(within_x * within_y, axis=nav_axes)

        uvw_in_a_pattern = da.logical_and(uvw_in_a_pattern, within_gnomonic_bounds)

        with ProgressBar():
            print("Finding zone axes that are in some pattern:", file=sys.stdout)
            uvw_in_a_pattern = uvw_in_a_pattern.compute()
        uvw_in_pattern = uvw_is_upper[..., uvw_in_a_pattern]
        uvw_d = uvw_d[..., uvw_in_a_pattern, :]

        # Visible zone axes
        uvw_miller = uvw_miller[uvw_in_a_pattern]

        with ProgressBar():
            print(
                "Calculating detector coordinates for bands and zone axes:",
                file=sys.stdout,
            )
            hkl_d, hkl_in_pattern, uvw_d, uvw_in_pattern = da.compute(
                [hkl_d, hkl_in_pattern, uvw_d, uvw_in_pattern]
            )[0]

        # Max. gnomonic radius to consider
        max_r_gnomonic = np.max(detector.r_max)

        lines = KikuchiPatternLine(
            hkl=ref2,
            hkl_detector=Vector3d(hkl_d),
            in_pattern=hkl_in_pattern,
            max_r_gnomonic=max_r_gnomonic,
        )

        zone_axes = KikuchiPatternZoneAxis(
            uvw=uvw_miller,
            uvw_detector=Vector3d(uvw_d),
            in_pattern=uvw_in_pattern,
            max_r_gnomonic=max_r_gnomonic,
        )

        simulation = GeometricalKikuchiPatternSimulation(
            detector=detector,
            rotations=rotations,
            reflectors=visible_reflectors,
            lines=lines,
            zone_axes=zone_axes,
        )

        return simulation

    def plot(
        self,
        projection: str | None = "stereographic",
        mode: str | None = "lines",
        hemisphere: str | None = "upper",
        scaling: str | None = "linear",
        figure: "mfigure.Figure | Plotter | None" = None,
        return_figure: bool = False,
        backend: str = "matplotlib",
        show_plotter: bool = True,
        color: str = "k",
        **kwargs,
    ) -> "mfigure.Figure | Plotter | None":
        """Plot reflectors as lines or bands in the stereographic or
        spherical projection.

        Parameters
        ----------
        projection
            Either ``"stereographic"`` (default) or ``"spherical"``.
        mode
            Either ``"lines"`` (default) or ``"bands"``. The latter
            option requires that :attr:`reflectors` have Bragg angles
            (:attr:`~diffsims.crystallography.ReciprocalLatticeVector.theta`)
            calculated.
        hemisphere
            Which hemisphere to plot when
            ``projection="stereographic"``. Options are ``"upper"``
            (default), ``"lower"`` or ``"both"``. Ignored if ``figure``
            is given.
        scaling
            Intensity scaling of the band kinematical intensities,
            either ``"linear"`` (default), :math:`|F|`, ``"square"``,
            :math:`|F|^2`, or ``None``, giving all bands the same
            intensity. The intensity range is [0, highest intensity].
        figure
            An existing :class:`~matplotlib.figure.Figure` or
            :class:`~pyvista.Plotter` to add the reflectors to. If not
            given, a new figure is created.
        return_figure
            Whether to return the figure. Default is ``False``. This is
            a :class:`~matplotlib.figure.Figure` if
            ``backend=="matplotlib"`` or a :class:`~pyvista.Plotter` if
            ``backend=="pyvista"``.
        backend
            Which plotting library to use when
            ``projection="spherical"``, either ``"matplotlib"``
            (default) or ``"pyvista"``. The latter option requires that
            PyVista is installed.
        show_plotter
            Whether to show the :class:`~pyvista.Plotter` when
            ``projection="spherical"`` and ``backend="pyvista"``.
            Default is ``True``.
        color
            Color to give reflectors. Either a string signifying a valid
            Matplotlib color or ``"phase"``, which then uses the
            :attr:`~orix.crystal_map.Phase.color_rgb` of the
            :attr:`~kikuchipy.simulations.KikuchiPatternSimulator.phase`.
            Default is black (``"k"``). Only used with Matplotlib.
        **kwargs
            Keyword arguments passed to
            :meth:`~orix.vector.Vector3d.draw_circle`.

        Returns
        -------
        figure
            If ``return_figure=True``, a
            :class:`~matplotlib.figure.Figure` or a
            :class:`~pyvista.Plotter` is returned.
        """
        if (
            projection == "spherical"
            and backend == "pyvista"
            and dependency_version["pyvista"] is None
        ):  # pragma: no cover
            raise ImportError("PyVista is not installed")

        ref = self._reflectors

        allowed_modes = ["lines", "bands"]
        if mode not in allowed_modes:
            raise ValueError(f"Unknown `mode`, options are {allowed_modes}")
        if mode == "bands" and np.isnan(ref.theta[0]):
            raise ValueError(
                "Requires that reflectors have Bragg angles calculated with "
                "`self.reflectors.calculate_theta()`."
            )

        if scaling == "linear":
            intensity = abs(self.reflectors.structure_factor)
            order = np.argsort(intensity)
            scaling_title = "|F_hkl|"
        elif scaling == "square":
            factor = self.reflectors.structure_factor
            intensity = abs(factor * factor.conjugate())
            order = np.argsort(intensity)
            scaling_title = "|F_hkl|^2"
        elif scaling is None:
            intensity = np.ones(self.reflectors.size)
            order = np.arange(ref.size)
            scaling_title = None
        else:
            raise ValueError(
                "Unknown `scaling`, options are 'linear', 'square' or None"
            )

        if color == "phase":
            color_rgb = self.phase.color_rgb
        else:
            color_rgb = mcolors.to_rgb(color)
        if scaling in ["linear", "square"]:
            intensity_scaled = intensity / np.max(intensity)
        else:
            intensity_scaled = intensity.copy()
        rgb = np.full((ref.size, 3), color_rgb)  # RGB
        color_rgba = np.column_stack((rgb, intensity_scaled[:, np.newaxis]))

        # Sort reflectors so that weakest are plotted first
        ref = ref[order].deepcopy()
        color_rgba = color_rgba[order]

        if projection == "stereographic":
            kwargs.setdefault("color", color_rgba)
            if all(i not in kwargs for i in ["linewidth", "lw"]):
                kwargs.setdefault("linewidth", 0.5)

            if mode == "lines":
                if figure is None:
                    figure = ref.draw_circle(
                        hemisphere=hemisphere, return_figure=True, **kwargs
                    )
                else:
                    ref.draw_circle(figure=figure, **kwargs)
            else:  # bands
                v = Vector3d(ref)
                theta = ref.theta
                if figure is None:
                    figure = v.draw_circle(
                        opening_angle=np.pi / 2 - theta,
                        hemisphere=hemisphere,
                        return_figure=True,
                        **kwargs,
                    )
                else:
                    v.draw_circle(
                        opening_angle=np.pi / 2 - theta, figure=figure, **kwargs
                    )
                v.draw_circle(opening_angle=np.pi / 2 + theta, figure=figure, **kwargs)
        elif projection == "spherical":
            figure = _plot_spherical(
                mode,
                ref,
                color_rgba,
                backend,
                figure,
                show_plotter,
                scaling_title,
                intensity[order],
            )
        else:
            raise ValueError(
                "Unknown `projection`, options are 'stereographic' and 'spherical'"
            )

        if return_figure:
            return figure

    def _raise_if_no_theta(self):
        if np.isnan(self.reflectors.theta[0]):
            raise ValueError(
                "Reflectors have no Bragg angles. Calculate with "
                "`diffsims.crystallography.ReciprocalLatticeVector.calculate_theta()`."
            )

    def _raise_if_no_structure_factor(self):
        if np.isnan(self.reflectors.structure_factor[0]):
            raise ValueError(
                "Reflectors have no structure factors. Calculate with "
                "`diffsims.crystallography.ReciprocalLatticeVector."
                "calculate_structure_factor()`."
            )


def _plot_spherical(
    mode: str,
    ref: ReciprocalLatticeVector,
    color: np.ndarray,
    backend: str,
    figure: "mfigure.Figure | Plotter | None",
    show_plotter: bool,
    scaling_title: str,
    intensity: np.ndarray,
) -> None:
    v = Vector3d(ref).unit

    steps = 101
    if mode == "lines":
        circles = v.get_circle(steps=steps).data
    else:  # bands
        theta = ref.theta
        circles = (
            v.get_circle(opening_angle=np.pi / 2 - theta, steps=steps).data,
            v.get_circle(opening_angle=np.pi / 2 + theta, steps=steps).data,
        )

    colors = ["r", "g", "b"]
    labels = ["e1", "e2", "e3"]

    if backend == "matplotlib":
        if figure is not None:
            ax = figure.axes[0]
        else:
            figure, ax = plt.subplots(subplot_kw=dict(projection="3d"))
        if mode == "lines":
            for i, ci in enumerate(circles):
                ax.plot3D(*ci.T, c=color[i])
        else:  # bands
            for i, (c1i, c2i) in enumerate(zip(*circles)):
                ax.plot3D(*c1i.T, c=color[i])
                ax.plot3D(*c2i.T, c=color[i])
        ax.axis("off")
        ax.set_xlim((-1, 1))
        ax.set_ylim((-1, 1))
        ax.set_zlim((-1, 1))
        ax.set_box_aspect((1, 1, 1))
        ax.azim = -90
        ax.elev = 90
        arrow_kwargs = dict(mutation_scale=20, arrowstyle="-|>", linewidth=1)
        ha = ["left", "center", "center"]
        va = ["center", "bottom", "bottom"]
        for i in range(3):
            data = np.zeros((3, 2))
            data[i, 0] = 1
            data[i, 1] = 1.5
            arrow = Arrow3D(
                *data, color=colors[i], label=labels[i] + " axis", **arrow_kwargs
            )
            ax.add_artist(arrow)
            ax.text3D(
                *data[:, 1],
                s=labels[i],
                color=colors[i],
                label=labels[i] + " label",
                ha=ha[i],
                va=va[i],
            )
    else:  # pyvista
        import pyvista as pv

        if figure is None:
            figure = pv.Plotter()
            figure.add_axes(
                color="k", xlabel=labels[0], ylabel=labels[1], zlabel=labels[2]
            )
            sphere = pv.Sphere(radius=0.99)
            figure.add_mesh(sphere, color="w", lighting=False)
            figure.disable_shadows()
            figure.set_background("w")
            figure.set_viewup((0, 1, 0))
        else:
            # Assume that the existing plot has a unit sphere
            v = Vector3d(circles)
            circles = Vector3d.from_polar(v.azimuth, v.polar, radial=1.01).data

        if mode == "lines":
            circles_shape = circles.shape[:-1]
            circles = circles.reshape((-1, 3))
            lines = np.arange(circles.shape[0]).reshape(circles_shape)
        else:  # bands
            circles = np.vstack(circles)
            circles_shape = circles.shape[:-1]
            circles = circles.reshape((-1, 3))
            lines = np.arange(circles.shape[0]).reshape(circles_shape)
            intensity = np.tile(intensity, 2)

        if scaling_title is None:
            mesh_kw = dict(show_scalar_bar=False, cmap="gray")
        else:
            mesh_kw = dict(
                scalar_bar_args=dict(title=scaling_title, color="k"),
                clim=[0, np.max(intensity)],
                cmap="gray_r",
            )

        # Create mesh from vertices (3D coordinates) and line
        # connectivity arrays
        lines = np.insert(lines, 0, steps, axis=1)
        lines = lines.ravel()
        mesh = pv.PolyData(circles, lines=lines)
        figure.add_mesh(mesh, scalars=intensity, **mesh_kw)

        if show_plotter:
            figure.show()

    return figure


# ------------------- Numba-accelerated functions -------------------- #


@nb.njit(
    nb.float64[:](nb.float64[:], nb.float64[:, :], nb.float64[:, :], nb.float64[:]),
    cache=True,
    parallel=True,
    fastmath=True,
    nogil=True,
)
def get_pattern(intensity, xyz_hemi, xyz_reflector, theta_reflector):
    theta2 = np.pi / 2
    theta1 = theta2 - theta_reflector
    n = xyz_hemi.shape[0]
    m = xyz_reflector.shape[0]
    pattern = np.zeros(n, dtype=np.float64)
    for i in nb.prange(m):
        for j in range(n):
            D = vec_dot(xyz_reflector[i], xyz_hemi[j])
            if np.abs(D) <= 1e-7:
                pattern[j] = pattern[j] + 0.5 * intensity[i]
            else:
                angle = np.arccos(D)
                if angle <= theta2 and angle >= theta1[i]:
                    pattern[j] = pattern[j] + intensity[i]
    return pattern
