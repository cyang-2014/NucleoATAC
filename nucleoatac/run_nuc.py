"""
Script to call nucleosome positions-- track making, nucleosome calling, and nfr calling!

@author: Alicia Schep
"""
##### IMPORT MODULES #####
# import necessary python modules
import matplotlib as mpl
mpl.use('PS')
import multiprocessing as mp
import numpy as np
import traceback
import itertools
import pysam
from pyatac.utils import shell_command,read_chrom_sizes_from_bam
from pyatac.chunk import ChunkList
from nucleoatac.Occupancy import FragmentMixDistribution, OccupancyCalcParams
from nucleoatac.NucleosomeCalling import NucChunk, NucParameters
from pyatac.fragmentsizes import FragmentSizes
from pyatac.bias import PWM
from nucleoatac.VMat import VMat

def _nucHelper(arg):
    """function to get occupancy for a set of bed regions

    """
    (chunk, params) = arg
    try:
        nuc = NucChunk(chunk)
        nuc.process(params)
        if params.no_occ:
            out = {'nucpos' : [nuc.nuc_collection[i] for i in sorted(nuc.nonredundant)], 'nucpos.redundant' : [nuc.nuc_collection[i] for i in sorted(nuc.redundant)],
                               'nucleoatac_signal' : nuc.norm_signal, 'nucleoatac_raw' : nuc.nuc_signal, 'nucleoatac_background' : nuc.bias,
                               'nucleoatac_signal.smooth' : nuc.smoothed}
        else:
            out = {'nucpos' : [nuc.nuc_collection[i] for i in sorted(nuc.nonredundant)], 'nucpos.redundant' : [nuc.nuc_collection[i] for i in sorted(nuc.redundant)],
                               'nfrpos' : [nuc.nfrs[i] for i in sorted(nuc.nfrs.keys())],
                               'nucleoatac_signal' : nuc.norm_signal, 'occ' : nuc.occ, 'nucleoatac_raw' : nuc.nuc_signal, 'nucleoatac_background' : nuc.bias,
                               'nucleoatac_signal.smooth' : nuc.smoothed}
        nuc.removeData()
    except Exception as e:
        print('Caught exception when processing:\n'+  chunk.asBed()+"\n")
        traceback.print_exc()
        print()
        raise e
    return out



def _writeOcc(track_queue, out):
    out_handle = open(out + '.nucleoatac_occ.bedgraph','a')
    try:
        for track in iter(track_queue.get, 'STOP'):
            track.write_track(out_handle)
            track_queue.task_done()
    except Exception, e:
        print('Caught exception when writing occupancy track\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True


def _writeNucSig(track_queue, out):
    out_handle = open(out + '.nucleoatac_signal.bedgraph','a')
    try:
        for track in iter(track_queue.get, 'STOP'):
            track.write_track(out_handle)
            track_queue.task_done()
    except Exception, e:
        print('Caught exception when writing NucleoATAC signal track\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True


def _writeBackground(track_queue, out):
    out_handle = open(out + '.nucleoatac_background.bedgraph','a')
    try:
        for track in iter(track_queue.get, 'STOP'):
            track.write_track(out_handle)
            track_queue.task_done()
    except Exception, e:
        print('Caught exception when writing NucleoATAC background track\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True


def _writeSmooth(track_queue, out):
    out_handle = open(out + '.nucleoatac_signal.smooth.bedgraph','a')
    try:
        for track in iter(track_queue.get, 'STOP'):
            track.write_track(out_handle)
            track_queue.task_done()
    except Exception, e:
        print('Caught exception when writing smoothed NucleoATAC signal track\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True

def _writeRaw(track_queue, out):
    out_handle = open(out + '.nucleoatac_raw.bedgraph','a')
    try:
        for track in iter(track_queue.get, 'STOP'):
            track.write_track(out_handle)
            track_queue.task_done()
    except Exception, e:
        print('Caught exception when writing un-normalized NucleoATAC signal track\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True



def _writeNucPos(pos_queue, out):
    out_handle = open(out + '.nucpos.bed','a')
    try:
        for poslist in iter(pos_queue.get, 'STOP'):
            for pos in poslist:
                pos.write(out_handle)
            pos_queue.task_done()
    except Exception, e:
        print('Caught exception when writing nucleosome position file\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True

def _writeNucPosRedundant(pos_queue, out):
    out_handle = open(out + '.nucpos.redundant.bed','a')
    try:
        for poslist in iter(pos_queue.get, 'STOP'):
            for pos in poslist:
                pos.write(out_handle)
            pos_queue.task_done()
    except Exception, e:
        print('Caught exception when writing redundant nucleosome position file\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True



def _writeNFRPos(pos_queue, out):
    out_handle = open(out + '.nfrpos.bed','a')
    try:
        for poslist in iter(pos_queue.get, 'STOP'):
            for pos in poslist:
                pos.write(out_handle)
            pos_queue.task_done()
    except Exception, e:
        print('Caught exception when writing occupancy track\n')
        traceback.print_exc()
        print()
        raise e
    out_handle.close()
    return True

_writeFuncs = {'nucpos' : _writeNucPos, 'nucpos.redundant' : _writeNucPosRedundant, 'nfrpos' : _writeNFRPos,
               'nucleoatac_signal' : _writeNucSig, 'occ' : _writeOcc, 'nucleoatac_raw' : _writeRaw, 'nucleoatac_background' : _writeBackground,
               'nucleoatac_signal.smooth' : _writeSmooth}


def run_nuc(args, bases = 500000):
    """run occupancy calling

    """
    vmat = VMat.open(args.vmat)
    chrs = read_chrom_sizes_from_bam(args.bam)
    pwm = PWM.open(args.pwm)
    chunks = ChunkList.read(args.bed, chromDict = chrs, min_offset = vmat.mat.shape[1] + vmat.upper/2 + max(pwm.up,pwm.down), min_length = args.nuc_sep * 2)
    chunks.merge()
    maxQueueSize = max(2,int(2 * bases / np.mean([chunk.length() for chunk in chunks])))
    fragment_dist = FragmentMixDistribution(0, upper = vmat.upper)
    if args.sizes is not None:
        tmp = FragmentSizes.open(args.sizes)
        fragment_dist.fragmentsizes = FragmentSizes(0, vmat.upper, vals = tmp.get(0,vmat.upper))
    else:
        fragment_dist.getFragmentSizes(args.bam, chunks)
    if args.occ_track is None:
        fragment_dist.modelNFR()
    if not args.no_occ and args.occ_track is None:
        occ_params = OccupancyCalcParams(0, vmat.upper, fragment_dist)
        params = NucParameters(vmat = vmat, fragmentsizes = fragment_dist.fragmentsizes, bam = args.bam, fasta = args.fasta, pwm = args.pwm,
                           occ_params = occ_params, no_occ = args.no_occ,
                           sd = args.sd, nonredundant_sep = args.nuc_sep,redundant_sep = args.redundant_sep,
                           min_z = args.min_z, max_nfr_occ = args.max_nfr_occ, min_lr = args.min_lr)
    else:
        params = NucParameters(vmat = vmat, fragmentsizes = fragment_dist.fragmentsizes, bam = args.bam, fasta = args.fasta, pwm = args.pwm,
                           occ_track = args.occ_track, no_occ = args.no_occ,
                           sd = args.sd, nonredundant_sep = args.nuc_sep, redundant_sep = args.redundant_sep,
                           min_z = args.min_z, max_nfr_occ = args.max_nfr_occ, min_lr = args.min_lr )
    sets = chunks.split( bases = bases)
    pool1 = mp.Pool(processes = max(1,args.cores-1))
    if args.write_all:
        outputs = ['nucpos','nucpos.redundant','nucleoatac_signal','nucleoatac_signal.smooth',
                       'nucleoatac_background','nucleoatac_raw']
    else:
        outputs = ['nucpos','nucpos.redundant','nucleoatac_signal','nucleoatac_signal.smooth']
    if not params.no_occ:
        outputs.append('nfrpos')
    if params.occ_track is None and not params.no_occ:
        outputs.append('occ')
    handles = {}
    write_queues = {}
    write_processes = {}
    for i in outputs:
        if i not in ['nucpos','nucpos.redundant','nfrpos']:
            handles[i] = open(args.out + '.'+i+'.bedgraph','w')
        else:
            handles[i] = open(args.out + '.'+i+'.bed','w')
        handles[i].close()
        write_queues[i] = mp.JoinableQueue(maxsize = maxQueueSize)
        write_processes[i] = mp.Process(target = _writeFuncs[i], args=(write_queues[i], args.out))
        write_processes[i].start()
    for j in sets:
        tmp = pool1.map(_nucHelper, zip(j,itertools.repeat(params)))
        for result in tmp:
            for i in outputs:
                write_queues[i].put(result[i])
    pool1.close()
    pool1.join()
    for i in outputs:
        write_queues[i].put('STOP')
        write_processes[i].join()
        if i not in ['nucpos','nucpos.redundant','nfrpos']:
            pysam.tabix_compress(args.out + '.' + i + '.bedgraph', args.out +  '.' + i + '.bedgraph.gz',force = True)
            shell_command('rm ' + args.out +  '.' + i + '.bedgraph')
            pysam.tabix_index(args.out +  '.' + i + '.bedgraph.gz', preset = "bed", force = True)






