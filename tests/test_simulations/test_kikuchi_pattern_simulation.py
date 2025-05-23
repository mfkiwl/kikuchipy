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

import logging

from diffpy.structure import Atom, Lattice, Structure
from diffsims.crystallography import ReciprocalLatticeVector
import matplotlib.collections as mcollections
import matplotlib.pyplot as plt
import matplotlib.text as mtext
import numpy as np
from orix.crystal_map import Phase
from orix.quaternion import Rotation

import kikuchipy as kp


def setup_reflectors() -> ReciprocalLatticeVector:
    """Return simulator used in `setup_method` of multiple test classes."""
    phase = Phase(
        name="al",
        space_group=225,
        structure=Structure(
            atoms=[Atom("Al", [0, 0, 0])],
            lattice=Lattice(4.05, 4.05, 4.05, 90, 90, 90),
        ),
    )
    g = ReciprocalLatticeVector(phase, hkl=((1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1)))
    g.sanitise_phase()
    g = g.symmetrise()
    g.calculate_structure_factor()
    g.calculate_theta(20e3)
    return g


class TestGeometricalKikuchiPatternSimulation:
    """General features of the GeometricalKikuchiPatternSimulation
    class.
    """

    def setup_method(self):
        self.reflectors = setup_reflectors()
        self.detector = kp.detectors.EBSDDetector(shape=(60, 60))
        self.rotations = Rotation.stack(
            (Rotation.from_axes_angles([(0, 0, 1), (0, 0, -1)], np.deg2rad(80)),) * 2
        )

    def test_init_attributes_repr(self):
        simulator = kp.simulations.KikuchiPatternSimulator(self.reflectors)
        det = self.detector
        rot = Rotation.from_axes_angles((0, 0, 1), np.deg2rad(80))
        sim = simulator.on_detector(det, rot)

        assert isinstance(sim.detector, kp.detectors.EBSDDetector)
        assert isinstance(sim.rotations, Rotation)
        assert isinstance(sim.reflectors, ReciprocalLatticeVector)

        assert sim.navigation_shape == rot.shape == (1,)

        # Properties are deep copied
        assert not np.may_share_memory(sim.detector.pc, det.pc)
        assert not np.may_share_memory(sim.rotations.data, rot.data)
        assert not np.may_share_memory(sim.reflectors.data, simulator.reflectors.data)

        # But values are unchanged
        np.testing.assert_almost_equal(sim.detector.pc, det.pc)
        np.testing.assert_almost_equal(sim.rotations.data, rot.data)

        # Only half of vectors are within pattern
        assert sim.reflectors.size == 25 < self.reflectors.size

        sim_repr = repr(sim)
        sim_repr = sim_repr.split("\n")
        assert "\n".join(sim_repr[:4]) == (
            "GeometricalKikuchiPatternSimulation (1,):\n"
            "ReciprocalLatticeVector (25,), al (m-3m)\n"
            "[[ 1.  1.  1.]\n"
            " [-1.  1.  1.]"
        )

        # Navigation shape
        sim2 = simulator.on_detector(det, Rotation.random((2, 3)))
        assert sim2.navigation_shape == (2, 3)
        sim_repr2 = repr(sim2)
        sim_repr2 = sim_repr2.split("\n")
        assert sim_repr2[0] == "GeometricalKikuchiPatternSimulation (2, 3):"

    def test_get_coordinates(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)
        sim = simulator.on_detector(self.detector, self.rotations)
        assert sim.reflectors.size == 4

        # Check Kikuchi line coordinates of two {200} lines (start-end)
        assert np.allclose(
            sim.lines_coordinates(),
            [[24.4, -11.9, 38.0, 70.3], [-12.1, 26.6, 67.2, 11.7]],
            atol=0.1,
        )
        assert np.allclose(
            sim.lines_coordinates((1, 1)),
            [[21.0, 70.3, 34.6, -11.9], [-8.2, 11.7, 71.1, 26.6]],
            atol=0.1,
        )

        # Check zone axis coordinates of two <100> zone axes
        assert np.allclose(sim.zone_axes_coordinates(), [29.5, 18.76], atol=0.01)
        assert np.allclose(sim.zone_axes_coordinates((1, 1)), [29.5, 18.76], atol=0.01)

    def test_plot(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)
        sim = simulator.on_detector(self.detector, self.rotations)

        fig = sim.plot(
            pattern=np.random.random(self.detector.size).reshape(self.detector.shape),
            return_figure=True,
        )
        assert isinstance(fig, plt.Figure)

        plt.close("all")

    def test_matplotlib_text_logger_filters(self):
        filters = logging.getLogger("matplotlib.text").filters
        assert filters == [kp.simulations.DisableMatplotlibWarningFilter]

    def test_as_collections_gnomonic(self):
        s = kp.data.nickel_ebsd_small()

        g = ReciprocalLatticeVector(s.xmap.phases[0], [[1, 1, 1]])
        g = g.symmetrise()
        simulator = kp.simulations.KikuchiPatternSimulator(g)

        rot = s.xmap.rotations.reshape(*s.xmap.shape)

        det_2d = s.detector
        det_single = det_2d.deepcopy()
        det_single.pc = det_2d.pc[0, 1]

        sim_single = simulator.on_detector(det_single, rot[0, 1])
        sim_single_rot_2d = simulator.on_detector(det_single, rot)

        za_coords_single = sim_single.zone_axes_coordinates(coordinates="gnomonic")
        za_coords_single_rot_2d = sim_single_rot_2d.zone_axes_coordinates(
            (0, 1), coordinates="gnomonic"
        )
        assert np.all(np.isin(za_coords_single, za_coords_single_rot_2d))


class TestAsCollections:
    """Getting lines, zone axes, zone axes labels and PC as Matplotlib
    collections.
    """

    def setup_method(self):
        self.reflectors = setup_reflectors()
        self.detector = kp.detectors.EBSDDetector(shape=(60, 60))
        self.rotations = Rotation.stack(
            (Rotation.from_axes_angles([(0, 0, 1), (0, 0, -1)], np.deg2rad(80)),) * 2
        )

    def test_as_collections(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)
        sim = simulator.on_detector(self.detector, self.rotations)

        assert sim.navigation_shape == (2, 2)
        assert sim.reflectors.size == 4

        # Only lines
        coll1 = sim.as_collections()
        assert isinstance(coll1, list)
        assert np.all([isinstance(c, mcollections.LineCollection) for c in coll1])

        # Only paths
        coll2 = sim.as_collections(lines=False, zone_axes=True)
        assert np.all([isinstance(c, mcollections.PathCollection) for c in coll2])

        # Only texts
        coll3 = sim.as_collections(lines=False, zone_axes_labels=True)
        assert np.all([isinstance(c, mtext.Text) for c in coll3[0]])

    def test_index(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)
        sim = simulator.on_detector(self.detector, self.rotations)

        # Sanity check
        assert np.allclose(self.rotations[0, 0].data, self.rotations.data[0, 1])
        assert np.allclose(self.rotations[1, 0].data, self.rotations.data[1, 1])

        # Extract Kikuchi line paths (start and end coordinates) and
        # ensure they are equal for equal rotations (?!)
        paths = np.zeros((2, 2, 2, 2, 2))
        for idx in np.ndindex(*sim.navigation_shape):
            coll_i = sim.as_collections(idx)
            path = coll_i[0].get_paths()
            for j in range(paths.shape[2]):
                paths[idx, j] = path[j].vertices
        assert np.allclose(paths[0, 0], paths[1, 0])
        assert np.allclose(paths[0, 1], paths[1, 1])

    def test_kwargs(self):
        simulator = kp.simulations.KikuchiPatternSimulator(self.reflectors)
        sim = simulator.on_detector(self.detector, self.rotations)

        coll = sim.as_collections(
            zone_axes=True,
            zone_axes_labels=True,
            lines_kwargs={"linewidth": 2},  # Default is 1
            zone_axes_kwargs={"fc": "r", "ec": "b"},
            zone_axes_labels_kwargs={"fontsize": 5},  # Default is 10
        )

        assert coll[0].get_linewidth() == 2
        assert np.allclose(coll[1].get_facecolor()[0][:3], [1, 0, 0])
        assert np.allclose(coll[1].get_edgecolor()[0][:3], [0, 0, 1])
        assert coll[2][0].get_fontsize() == 5

    def test_coordinates(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)
        sim = simulator.on_detector(self.detector, self.rotations)

        coll1 = sim.as_collections()
        coll2 = sim.as_collections(
            coordinates="gnomonic", zone_axes=True, zone_axes_labels=True
        )

        # Extract the path of the first Kikuchi line and assert that
        # start-end coordinates are as expected
        coords1 = coll1[0].get_paths()[0].vertices.ravel()
        assert np.allclose(coords1, [24.4, -11.92, 38.0, 70.3], atol=0.1)
        coords2 = coll2[0].get_paths()[0].vertices.ravel()
        assert np.allclose(coords2, [-0.2, 1.4, 0.3, -1.4], atol=0.1)

        # Extract gnomonic coordinates of zone axes and zone axes labels
        za_coords2 = coll2[1].get_paths()[0].vertices
        assert np.allclose(za_coords2.mean(axis=0), [0, 0.36], atol=0.01)
        za_labels_coords2 = coll2[2][0]
        assert np.allclose(za_labels_coords2.get_position(), [0, 0.42], atol=0.01)

    def test_zone_axes_as_collections_gnomonic(self):
        s = kp.data.nickel_ebsd_small()

        # Indices into zone axes paths later on depend on reflectors and
        # their order!
        g = ReciprocalLatticeVector(s.xmap.phases[0], [[1, 1, 1]])
        g = g.symmetrise()
        simulator = kp.simulations.KikuchiPatternSimulator(g)

        rot = s.xmap.rotations.reshape(*s.xmap.shape)

        idx = (0, 1)
        idx_single = 0
        idx_2d = 3

        det_2d = s.detector
        det_single = det_2d.deepcopy()
        det_single.pc = det_2d.pc[idx]

        sim_2d = simulator.on_detector(det_2d, rot)
        sim_single = simulator.on_detector(det_single, rot[idx])
        sim_single_rot_2d = simulator.on_detector(det_single, rot)

        kw = {
            "coordinates": "gnomonic",
            "lines": False,
            "zone_axes": True,
            "zone_axes_labels": True,
        }

        coll_2d = sim_2d.as_collections(idx, **kw)
        coll_single = sim_single.as_collections((0,), **kw)
        coll_single_rot_2d = sim_single_rot_2d.as_collections(idx, **kw)

        # Zone axes labels
        za_labels_2d = [label.get_text() for label in coll_2d[1]]
        za_labels_single = [label.get_text() for label in coll_single[1]]
        za_labels_single_rot_2d = [label.get_text() for label in coll_single_rot_2d[1]]
        assert np.all(za_labels_2d == za_labels_single_rot_2d)
        assert np.all(za_labels_2d[2:][::-1] == za_labels_single)

        # Zone axes
        za_2d_scatter_verts = coll_2d[0].get_paths()[idx_2d].vertices
        za_single_verts = coll_single[0].get_paths()[idx_single].vertices
        za_single_rot_2d_verts = coll_single_rot_2d[0].get_paths()[idx_2d].vertices
        assert np.allclose(za_2d_scatter_verts, za_single_verts)
        assert np.allclose(za_single_verts, za_single_rot_2d_verts)


class TestAsMarkers:
    """Getting lines, zone axes, zone axes labels and PC as HyperSpy
    markers.
    """

    def setup_method(self):
        self.reflectors = setup_reflectors()
        self.detector = kp.detectors.EBSDDetector(shape=(60, 60))
        self.rotations = Rotation.stack(
            (Rotation.from_axes_angles([(0, 0, 1), (0, 0, -1)], np.deg2rad(80)),) * 2
        )

    def test_as_markers(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)
        sim = simulator.on_detector(self.detector, self.rotations)

        # Default
        markers0 = sim.as_markers()
        assert len(markers0) == 1

        markers = sim.as_markers(
            zone_axes=True,
            zone_axes_labels=True,
            pc=True,
            lines_kwargs={"colors": "b"},
            zone_axes_kwargs={"color": "g"},
            zone_axes_labels_kwargs={"color": "y"},
            pc_kwargs={"color": "r"},
        )
        assert isinstance(markers, list)
        assert len(markers) == 4
        assert markers[0].kwargs["colors"] == "b"
        for marker, color in zip(markers[1:], ["g", "y", "r"]):
            assert marker.kwargs["color"] == (color,)

        line_segments = markers[0].kwargs["segments"]
        assert line_segments.shape == (2, 2)
        for idx in np.ndindex(sim.navigation_shape):
            assert line_segments[idx].shape == (2, 2, 2)

    def test_add_markers(self):
        hkl_sets = self.reflectors.get_hkl_sets()
        ref200 = self.reflectors[hkl_sets[2, 0, 0]]
        simulator = kp.simulations.KikuchiPatternSimulator(ref200)

        sim1d = simulator.on_detector(self.detector, self.rotations[0, 0])
        s = kp.signals.EBSD(
            np.random.random(self.detector.size).reshape(self.detector.shape)
        )
        markers1 = sim1d.as_markers(zone_axes=True, zone_axes_labels=True, pc=True)
        print(markers1[3].kwargs["offsets"].shape)
        s.add_marker(markers1, plot_marker=False, permanent=True)
        assert len(s.metadata.Markers) == 4
        s.plot()

        sim2d = simulator.on_detector(self.detector, self.rotations)
        n_patterns = np.prod(sim2d.navigation_shape)
        data2d = np.random.random(n_patterns * self.detector.size).reshape(
            sim2d.navigation_shape + self.detector.shape
        )
        s2 = kp.signals.EBSD(data2d)
        markers2 = sim2d.as_markers()
        s2.add_marker(markers2, plot_marker=False, permanent=True)
        assert len(s2.metadata.Markers) == 1
        s2.plot()

        plt.close("all")

    def test_pc_xy_offsets_single(self):
        simulator = kp.simulations.KikuchiPatternSimulator(self.reflectors)
        R = self.rotations
        det_shape_factor = np.array(self.detector.shape[::-1]) - 1

        sim = simulator.on_detector(self.detector, R)
        pc_offsets = sim._pc_xy_offsets()
        assert pc_offsets.shape == (2,)
        pc_expected = self.detector.pc_average[:2] * det_shape_factor
        assert np.allclose(pc_offsets, pc_expected)

    def test_pc_xy_offsets_multiple(self):
        simulator = kp.simulations.KikuchiPatternSimulator(self.reflectors)
        R = self.rotations
        det_shape_factor = np.array(self.detector.shape[::-1]) - 1

        det = self.detector.deepcopy()
        pc = np.arange(R.size * 3).reshape(*R.shape, 3)
        det.pc = pc
        sim = simulator.on_detector(det, R)
        pc_offsets = sim._pc_xy_offsets()
        assert pc_offsets.shape == det.navigation_shape
        for idx in np.ndindex(det.navigation_shape):
            idx_xy = idx[::-1]
            assert np.allclose(pc_offsets[idx_xy], pc[idx][:2] * det_shape_factor)
