#!/usr/bin/env python3

# Author Dingquan Yu
# This script is just to create msa and structural features for each sequences and store them in pickle
# #

import os
import pickle
import sys
from alphapulldown.objects import MonomericObject
import importlib
from absl import app
from absl import flags
from absl import logging

from alphafold.data.pipeline import DataPipeline
from alphafold.data.tools import hmmsearch
from alphafold.data import templates
import numpy as np
import os
from absl import logging, app
import numpy as np
from alphapulldown.utils import *
import contextlib
from datetime import datetime
import alphafold
from pathlib import Path
from colabfold.utils import DEFAULT_API_SERVER

@contextlib.contextmanager
def output_meta_file(file_path):
    """function that create temp file"""
    with open(file_path, "w") as outfile:
        yield outfile.name


def load_module(file_name, module_name):
    spec = importlib.util.spec_from_file_location(module_name, file_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


PATH_TO_RUN_ALPHAFOLD = os.path.join(
    os.path.dirname(alphafold.__file__), "run_alphafold.py"
)

try:
    run_af = load_module(PATH_TO_RUN_ALPHAFOLD, "run_alphafold")
except FileNotFoundError:
    PATH_TO_RUN_ALPHAFOLD = os.path.join(
        os.path.dirname(os.path.dirname(alphafold.__file__)), "run_alphafold.py"
    )

    run_af = load_module(PATH_TO_RUN_ALPHAFOLD, "run_alphafold")


flags = run_af.flags
flags.DEFINE_bool("save_msa_files", False, "save msa output or not")
flags.DEFINE_bool(
    "skip_existing", False, "skip existing monomer feature pickles or not"
)
flags.DEFINE_integer(
    "seq_index", None, "index of sequence in the fasta file, starting from 1"
)
flags.DEFINE_string(
    "new_uniclust_dir", None, "directory where new version of uniclust is stored"
)
flags.DEFINE_bool("use_mmseqs2",False,"Use mmseqs2 remotely or not. Default is False")

FLAGS = flags.FLAGS
MAX_TEMPLATE_HITS = 20

flags_dict = FLAGS.flag_values_dict()

def create_global_arguments(flags_dict):
    global uniref90_database_path
    global mgnify_database_path
    global bfd_database_path
    global small_bfd_database_path
    global pdb_seqres_database_path
    global template_mmcif_dir
    global obsolete_pdbs_path
    global pdb70_database_path
    global use_small_bfd
    global uniref30_database_path

    # Path to the Uniref30 database for use by HHblits.
    if FLAGS.uniref30_database_path is None:
        uniref30_database_path = os.path.join(
            FLAGS.data_dir, "uniref30", "UniRef30_2021_03"
        )
    else:
        uniref30_database_path = FLAGS.uniref30_database_path
    flags_dict.update({"uniref30_database_path": uniref30_database_path})

    if FLAGS.uniref90_database_path is None: 
        uniref90_database_path = os.path.join(
            FLAGS.data_dir, "uniref90", "uniref90.fasta"
        )
    else:
        uniref90_database_path = FLAGS.uniref90_database_path

    flags_dict.update({"uniref90_database_path": uniref90_database_path})

    # Path to the MGnify database for use by JackHMMER.
    if FLAGS.mgnify_database_path is None:
        mgnify_database_path = os.path.join(
            FLAGS.data_dir, "mgnify", "mgy_clusters_2022_05.fa"
        )
    else:
        mgnify_database_path = FLAGS.mgnify_database_path
    flags_dict.update({"mgnify_database_path": mgnify_database_path})

    # Path to the BFD database for use by HHblits.
    if FLAGS.bfd_database_path is None:
        bfd_database_path = os.path.join(
            FLAGS.data_dir,
            "bfd",
            "bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt",
        )
    else:
        bfd_database_path = FLAGS.bfd_database_path
    flags_dict.update({"bfd_database_path": bfd_database_path})

    # Path to the Small BFD database for use by JackHMMER.
    if FLAGS.small_bfd_database_path is None:
        small_bfd_database_path = os.path.join(
            FLAGS.data_dir, "small_bfd", "bfd-first_non_consensus_sequences.fasta"
        )
    else:
        small_bfd_database_path = FLAGS.small_bfd_database_path
    flags_dict.update({"small_bfd_database_path": small_bfd_database_path})

    if FLAGS.pdb_seqres_database_path is None:
        pdb_seqres_database_path = os.path.join(
            FLAGS.data_dir, "pdb_seqres", "pdb_seqres.txt"
        )
    else:
        pdb_seqres_database_path = FLAGS.pdb_seqres_database_path
    flags_dict.update({"pdb_seqres_database_path": pdb_seqres_database_path})

    # Path to a directory with template mmCIF structures, each named <pdb_id>.cif.
    if FLAGS.template_mmcif_dir is None:
        template_mmcif_dir = os.path.join(FLAGS.data_dir, "pdb_mmcif", "mmcif_files")
    else:
        template_mmcif_dir = FLAGS.template_mmcif_dir
    flags_dict.update({"template_mmcif_dir": template_mmcif_dir})

    # Path to a file mapping obsolete PDB IDs to their replacements.
    if FLAGS.obsolete_pdbs_path is None:
        obsolete_pdbs_path = os.path.join(FLAGS.data_dir, "pdb_mmcif", "obsolete.dat")
    else:
        obsolete_pdbs_path = FLAGS.obsolete_pdbs_path
    flags_dict.update({"obsolete_pdbs_path": obsolete_pdbs_path})

    # Path to pdb70 database
    if FLAGS.pdb70_database_path is None:
        pdb70_database_path = os.path.join(FLAGS.data_dir, "pdb70", "pdb70")
    else:
        pdb70_database_path = FLAGS.pdb70_database_path
    flags_dict.update({"pdb70_database_path": pdb70_database_path})
    use_small_bfd = FLAGS.db_preset == "reduced_dbs"

def create_pipeline():
    monomer_data_pipeline = DataPipeline(
        jackhmmer_binary_path=FLAGS.jackhmmer_binary_path,
        hhblits_binary_path=FLAGS.hhblits_binary_path,
        uniref90_database_path=uniref90_database_path,
        mgnify_database_path=mgnify_database_path,
        bfd_database_path=bfd_database_path,
        uniref30_database_path=uniref30_database_path,
        small_bfd_database_path=small_bfd_database_path,
        use_small_bfd=use_small_bfd,
        use_precomputed_msas=FLAGS.use_precomputed_msas,
        template_searcher=hmmsearch.Hmmsearch(
            binary_path=FLAGS.hmmsearch_binary_path,
            hmmbuild_binary_path=FLAGS.hmmbuild_binary_path,
            database_path=pdb_seqres_database_path,
        ),
        template_featurizer=templates.HmmsearchHitFeaturizer(
            mmcif_dir=template_mmcif_dir,
            max_template_date=FLAGS.max_template_date,
            max_hits=MAX_TEMPLATE_HITS,
            kalign_binary_path=FLAGS.kalign_binary_path,
            obsolete_pdbs_path=obsolete_pdbs_path,
            release_dates_path=None,
        ),
    )
    return monomer_data_pipeline


def check_existing_objects(output_dir, pickle_name):
    """check whether the wanted monomer object already exists in the output_dir"""
    return os.path.isfile(os.path.join(output_dir, pickle_name))


def create_and_save_monomer_objects(m, pipeline, flags_dict,use_mmseqs2=False):
    logging.info("You are using the new version")
    if FLAGS.skip_existing and check_existing_objects(
        FLAGS.output_dir, f"{m.description}.pkl"
    ):
        logging.info(f"Already found {m.description}.pkl in {FLAGS.output_dir} Skipped")
        pass
    else:
        metadata_output_path = os.path.join(
            FLAGS.output_dir,
            f"{m.description}_feature_metadata_{datetime.date(datetime.now())}.txt",
        )
        with output_meta_file(metadata_output_path) as meta_data_outfile:
            save_meta_data(flags_dict, meta_data_outfile)
        
        if not use_mmseqs2:
            m.make_features(
                pipeline,
                output_dir=FLAGS.output_dir,
                use_precomputed_msa=FLAGS.use_precomputed_msas,
                save_msa=FLAGS.save_msa_files,
            )
        else:
            logging.info("running mmseq now")
            m.make_mmseq_features(DEFAULT_API_SERVER=DEFAULT_API_SERVER,
            pdb70_database_path=pdb70_database_path,
            template_mmcif_dir=template_mmcif_dir,
            max_template_date=FLAGS.max_template_date,
            output_dir=FLAGS.output_dir)
        pickle.dump(m, open(f"{FLAGS.output_dir}/{m.description}.pkl", "wb"))
        del m


def iter_seqs(fasta_fns):
    for fasta_path in fasta_fns:
        with open(fasta_path, "r") as f:
            sequences, descriptions = parse_fasta(f.read())
            for seq, desc in zip(sequences, descriptions):
                yield seq, desc

def main(argv):
    try:
        Path(FLAGS.output_dir).mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        logging.info("Multiple processes are trying to create the same folder now.")
    
    flags_dict = FLAGS.flag_values_dict()
    create_global_arguments(flags_dict)
    if not FLAGS.use_mmseqs2:
        if not FLAGS.max_template_date:
            logging.info("You have not provided a max_template_date. Please specify a date and run again.")
            sys.exit()
        else:
            pipeline = create_pipeline()
            uniprot_database_path = os.path.join(FLAGS.data_dir, "uniprot/uniprot.fa")
            flags_dict.update({"uniprot_database_path": uniprot_database_path})
            if os.path.isfile(uniprot_database_path):
                uniprot_runner = create_uniprot_runner(
                    FLAGS.jackhmmer_binary_path, uniprot_database_path
                )
            else:
                logging.info(
                    f"Failed to find uniprot.fasta under {uniprot_database_path}. Please make sure your data_dir has been configured correctly."
                )
                sys.exit()
    else:
        
        pipeline=None
        uniprot_runner=None
        flags_dict=FLAGS.flag_values_dict()

    seq_idx = 0
    for curr_seq, curr_desc in iter_seqs(FLAGS.fasta_paths):
        seq_idx = seq_idx + 1 #yes, we're counting from 1
        if FLAGS.seq_index is None or \
            (FLAGS.seq_index == seq_idx):
                if curr_desc and not curr_desc.isspace():
                    curr_monomer = MonomericObject(curr_desc, curr_seq)
                    curr_monomer.uniprot_runner = uniprot_runner
                    create_and_save_monomer_objects(curr_monomer, pipeline, 
                    flags_dict,use_mmseqs2=FLAGS.use_mmseqs2)
        

if __name__ == "__main__":
    flags.mark_flags_as_required(
        ["fasta_paths", "output_dir","max_template_date","data_dir"]
    )
    app.run(main)
