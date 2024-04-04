try:
    import psi4
except ImportError:
    print("Psi4 is not installed. Cannot calculate RESP charge automatically.")
from rdkit import Chem
from typing import List
from ..utils.embedding import get_eqv_atoms
from ..settings import settings
from tempfile import TemporaryDirectory
import subprocess
from pathlib import Path
import shutil
import numpy as np


def get_resp_charge(rdmol, use_dft=True):
    eqv_atoms = get_eqv_atoms(rdmol, layers=4)
    eqv_sets = [set(atoms) for atoms in eqv_atoms]

    new_set = []
    for eqv_set in eqv_sets:
        if len(eqv_set) > 1 and eqv_set not in new_set:
            new_set.append(eqv_set)

    final_eqv_list = []
    for eqv_set in new_set:
        eqv_list = []
        for atom in eqv_set:
            eqv_list.append(atom+1)
        final_eqv_list.append(eqv_list)

    with TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        geom_list = []
        for atom in rdmol.GetAtoms():
            atom_idx = atom.GetIdx()
            atom_symbol = atom.GetSymbol()
            if len(atom_symbol) > 1:
                atom_symbol = f"{atom_symbol[0].upper()}{atom_symbol[1:].lower()}"
            atom_pos = rdmol.GetConformer().GetAtomPosition(atom_idx)
            geom_list.append(f"{atom_symbol} {atom_pos.x} {atom_pos.y} {atom_pos.z}\n")
        geom = "".join(geom_list)
        geom += "no_reorient\nno_com\n"
        formal_charge = Chem.GetFormalCharge(rdmol)
        mol = psi4.geometry(geom)
        mol.set_units(psi4.core.GeometryUnits.Angstrom)
        mol.set_molecular_charge(formal_charge)
        mol.set_multiplicity(1)
        mol.update_geometry()
        mol.set_name(f'conformer')

        psi4.core.clean()
        iomanager = psi4.core.IOManager()
        iomanager.set_default_path(str(tmppath))
        psi4.set_num_threads(settings['resp_threads'])
        psi4.set_memory(settings['resp_memory'])
        psi4.set_options({
            'e_convergence':        1e-8,
            'd_convergence':        1e-8,
            'dft_spherical_points': 590,
            'dft_radial_points':    99,
        })

        if use_dft:
            psi4.set_options({"pcm": True, "pcm_scf_type": "total"})
            psi4.pcm_helper("""Units = Angstrom
            Medium {
            SolverType = IEFPCM
            Solvent = water
            }
            Cavity {
            RadiiSet = UFF
            Type = GePol
            Scaling = False
            Area = 0.4
            Mode = Implicit
            }""")
            scf_e, scf_wfn = psi4.energy('b3lyp/def2-svp', molecule=mol, return_wfn=True)
        else:
            scf_e, scf_wfn = psi4.energy('scf/6-31G*', molecule=mol, return_wfn=True)

        psi4.fchk(scf_wfn, str(tmppath / "conformer.fchk"))

        isHeavy = False
        for atom in rdmol.GetAtoms():
            if atom.GetAtomicNum() > 18:
                isHeavy = True
                break

        with open(tmppath / "eqv_list.txt", "w") as f:
            for eqv in final_eqv_list:
                f.write(" ".join(map(str, eqv)) + "\n")

        with open(tmppath / "run_espfit.txt", "w") as f:
            f.write("7\n18\n5\n1\neqv_list.txt\n1\n")
            if isHeavy:
                f.write("\n")
            f.write("y\n0\n0\nq\n")

        subprocess.run("Multiwfn conformer.fchk < run_espfit.txt", shell=True, cwd=tmpdir)

        charges = np.loadtxt(tmppath / "conformer.chg", usecols=4)
    return charges