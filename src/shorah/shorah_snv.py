#!/usr/bin/env python3

# Copyright 2007-2018
# Niko Beerenwinkel,
# Nicholas Eriksson,
# Moritz Gerstung,
# Lukas Geyrhofer,
# Osvaldo Zagordi,
# Kerensa McElroy,
# ETH Zurich

# This file is part of ShoRAH.
# ShoRAH is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# ShoRAH is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with ShoRAH.  If not, see <http://www.gnu.org/licenses/>.


'''
    ------------
    Output:
    a file of raw snvs, parsed from the directory support,
    and a directory containing snvs resulting from strand
    bias tests with different sigma values
    ------------
'''

from __future__ import division
import glob
import gzip
import os
import shutil
import sys
import warnings
import shlex
from collections import namedtuple

import logging

# Try fetching fil exe with pkg resources
try:
    from pkg_resources import resource_filename
except ModuleNotFoundError:
    fil_exe = None
else:
    fil_exe = resource_filename(__name__, 'bin/fil')
# Try fetching fil exe with bash 'which'
if not fil_exe or not os.path.exists(fil_exe):
    fil_exe = shutil.which('fil')
    if not fil_exe:
        # Try fetching fil exe based on directory structure
        all_dirs = os.path.abspath(__file__).split(os.sep)
        base_dir = os.sep.join(all_dirs[:-all_dirs[::-1].index('shorah')])
        fil_exe = os.path.join(base_dir, 'bin', 'fil')
        if not os.path.exists(fil_exe):
            logging.error('Executable fil not found, compile first.')
            sys.exit('Executable fil not found, compile first.')


def segments(incr):
    """How many times is a window segment covered?
       Read it from coverage.txt generated by b2w
    """
    segCov1 = {}
    try:
        infile = open('coverage.txt')
    except IOError:
        logging.error('Coverage file generated by b2w not found.')
        sys.exit('Coverage file generated by b2w not found.')
    for f in infile:
        # window_file, reference, begin, end, value
        w, c, b, e, v = f.rstrip().split('\t')
        b = int(b)
        del([w, e, v])
        segs = [c + str(b), c + str(b + incr), c + str(b + incr * 2)]
        for i1, s1 in enumerate(segs):
            if s1 in segCov1:
                segCov1[s1][i1] = 1
            else:
                segCov1[s1] = [0, 0, 0]
                segCov1[s1][i1] = 1
    infile.close()
    return segCov1


def parseWindow(line, ref1, threshold=0.9):
    """SNVs from individual support files, getSNV will build
        the consensus SNVs
        It returns a dictionary called snp with the following structure
        key:   pos.allele (position on the reference file and mutated base)
        value: reference name, position, reference_base, mutated base,
               average number of reads, posterior times average n of reads
    """
    from Bio import SeqIO
    from re import search

    snp = {}
    SNP_id = namedtuple('SNP_id', ['pos', 'var'])
    reads = 0.0
    winFile, chrom, beg, end, cov = line.rstrip().split('\t')
    del([winFile, cov])
    filename = 'w-%s-%s-%s.reads-support.fas' % (chrom, beg, end)

    # take cares of locations/format of support file
    if os.path.exists(filename):
        pass
    elif os.path.exists('support/' + filename):
        filename = 'support/' + filename
    elif os.path.exists('support/' + filename + '.gz'):
        filename = 'support/' + filename + '.gz'
    elif os.path.exists(filename + '.gz'):
        filename = filename + '.gz'

    try:
        if filename.endswith('.gz'):
            window = gzip.open(
                filename, 'rb' if sys.version_info < (3, 0) else 'rt')
        else:
            window = open(filename, 'r')
    except IOError:
        logging.error('File not found')
        return snp

    beg = int(beg)
    end = int(end)
    refSlice = ref1[chrom][beg - 1:end]
    max_snv = -1
    # sequences in support file exceeding the posterior threshold
    for s in SeqIO.parse(window, 'fasta'):
        seq = str(s.seq).upper()
        match_obj = search('posterior=(.*)\s*ave_reads=(.*)', s.description)
        post, av = float(match_obj.group(1)), float(match_obj.group(2))
        if post > 1.0:
            warnings.warn('posterior = %4.3f > 1' % post)
            logging.warning('posterior = %4.3f > 1' % post)
        if post >= threshold:
            reads += av
            pos = beg
            tot_snv = 0
            for idx, v in enumerate(refSlice):  # iterate on the reference
                if v != seq[idx]:  # SNV detected, save it
                    tot_snv += 1
                    snp_id = SNP_id(pos=pos, var=seq[idx])
                    if snp_id in snp:
                        snp[snp_id][4] += av
                        snp[snp_id][5] += post * av
                    else:
                        snp[snp_id] = [chrom, pos, v, seq[idx], av, post * av]
                pos += 1
            if tot_snv > max_snv:
                max_snv = tot_snv

    logging.info('max number of snvs per sequence found: %d', max_snv)
    # normalize
    for k, v in snp.items():
        v[5] /= v[4]
        v[4] /= reads

    return snp


def getSNV(ref, segCov, incr, window_thresh=0.9):
    """Parses SNV from all windows and output the dictionary with all the
    information
    """
    snpD = {}
    single_window = False
    try:
        cov_file = open('coverage.txt')
    except IOError:
        logging.error('Coverage file generated by b2w not found')
        sys.exit('Coverage file generated by b2w not found')

    # cycle over all windows reported in coverage.txt
    for f in cov_file:
        snp = parseWindow(f, ref, window_thresh)  # snvs found on corresponding support file
        beg = int(f.split('\t')[2])
        end = int(f.split('\t')[3])
        if incr == 1:
            incr = end - beg + 1
            single_window = True
            logging.info('working on single window as invoked by amplian')

        for k in sorted(snp.keys()):
            # reference name, position, reference_base, mutated base,
            # average number of reads, posterior times average n of reads
            chrom, p, rf, var, av, post = snp[k]
            if k in snpD:
                if p < (beg + incr):
                    snpD[k][4][2] = av
                    snpD[k][5][2] = post
                elif p < (beg + incr * 2):
                    snpD[k][4][1] = av
                    snpD[k][5][1] = post
                else:
                    snpD[k][4][0] = av
                    snpD[k][5][0] = post
            else:
                if p < (beg + incr):
                    cov = segCov[chrom + str(beg)]
                    if cov == [1, 1, 1]:
                        snpD[k] = [chrom, p, rf, var, ['-', '-', av],
                                   ['-', '-', post]]
                    elif cov == [1, 0, 0]:
                        snpD[k] = [chrom, p, rf, var, ['*', '*', av],
                                   ['*', '*', post]]
                    elif cov == [1, 1, 0]:
                        snpD[k] = [chrom, p, rf, var, ['*', '-', av],
                                   ['*', '-', post]]
                elif p < (beg + incr * 2):
                    cov = segCov[chrom + str(beg + incr)]
                    if cov == [1, 1, 1]:
                        snpD[k] = [chrom, p, rf, var, ['-', av, '-'],
                                   ['-', post, '-']]
                    elif cov == [1, 1, 0]:
                        snpD[k] = [chrom, p, rf, var, ['*', av, '-'],
                                   ['*', post, '-']]
                    elif cov == [0, 1, 1]:
                        snpD[k] = [chrom, p, rf, var, ['-', av, '*'],
                                   ['-', post, '*']]
                    elif cov == [0, 1, 0]:
                        snpD[k] = [chrom, p, rf, var, ['*', av, '*'],
                                   ['*', post, '*']]
                else:
                    cov = segCov[chrom + str(beg + incr * 2)]
                    if cov == [1, 1, 1]:
                        snpD[k] = [chrom, p, rf, var, [av, '-', '-'],
                                   [post, '-', '-']]
                    elif cov == [0, 1, 1]:
                        snpD[k] = [chrom, p, rf, var, [av, '-', '*'],
                                   [post, '-', '*']]
                    elif cov == [0, 0, 1]:
                        snpD[k] = [chrom, p, rf, var, [av, '*', '*'],
                                   [post, '*', '*']]

        if single_window:
            break

    return snpD


def printRaw(snpD2, incr):
    """Print the SNPs as they are obtained from the support files produced
        with shorah (raw calls). raw_snv.txt has all of them, SNV.txt only
        those covered by at least two windows.
        If incr==1 (as called by amplian.py) SNV.txt has all of them too.
    """

    out = open('raw_snv.txt', 'w')
    out1 = open('SNV.txt', 'w')

    # deal with single windows from amplian.py first
    if incr == 1:
        header_row_p = ['Chromosome', 'Pos', 'Ref', 'Var', 'Freq', 'Post']
        out.write('\t'.join(header_row_p) + '\n')
        out1.write('\t'.join(header_row_p) + '\n')
        for k in sorted(snpD2.keys()):
            snp_here = snpD2[k]
            assert type(snp_here[4][0]) == str, 'Frequency found'
            assert type(snp_here[4][1]) == str, 'Frequency found'
            assert type(snp_here[4][2]) == float, 'Frequency not found'
            row_1 = snpD2[k][0] + '\t' + str(snpD2[k][1]) + '\t' + \
                snpD2[k][2] + '\t' + snpD2[k][3] + '\t'
            row_2 = '%6.4f\t%6.4f\n' % (snpD2[k][4][2], snpD2[k][5][2])
            out.write(row_1 + row_2)
            out1.write(row_1 + row_2)
        out.close()
        out1.close()
        return

    # here deal with multiple windows
    header_row_p = ['Chromosome', 'Pos', 'Ref', 'Var', 'Frq1', 'Frq2', 'Frq3',
                    'Pst1', 'Pst2', 'Pst3']
    out.write('\t'.join(header_row_p) + '\n')
    out1.write('\t'.join(header_row_p) + '\n')
    key = sorted(list(snpD2.keys()))
    for k in key:
        out.write(snpD2[k][0] + '\t' + str(snpD2[k][1]) + '\t' + snpD2[k][2] +
                  '\t' + snpD2[k][3])
        count = 0
        for i in range(3):
            if type(snpD2[k][4][i]) == float:
                freq = '\t%.4f' % snpD2[k][4][i]
                count += 1
            else:
                freq = '\t' + snpD2[k][4][i]
            out.write(freq)
        for i in range(3):
            if type(snpD2[k][5][i]) == float:
                post = '\t%.4f' % snpD2[k][5][i]
            else:
                post = '\t' + snpD2[k][5][i]
            out.write(post)
        out.write('\n')
        if count >= 2:
            out1.write(snpD2[k][0] + '\t' + str(snpD2[k][1]) + '\t' +
                       snpD2[k][2] + '\t' + snpD2[k][3])
            for i in range(3):
                if type(snpD2[k][4][i]) == float:
                    freq = '\t%.4f' % snpD2[k][4][i]
                else:
                    freq = '\t' + snpD2[k][4][i]
                out1.write(freq)
            for i in range(3):
                if type(snpD2[k][5][i]) == float:
                    post = '\t%.4f' % snpD2[k][5][i]
                else:
                    post = '\t' + snpD2[k][5][i]
                out1.write(post)
            out1.write('\n')
    out.close()
    out1.close()


def sb_filter(in_bam, sigma, amplimode="", drop_indels="", max_coverage=100000):
    """run strand bias filter calling the external program 'fil'
    """
    import subprocess
    # dn = sys.path[0]
    my_prog = shlex.quote(fil_exe)  # os.path.join(dn, 'fil')
    my_arg = ' -b ' + in_bam + ' -v ' + str(sigma) + amplimode + drop_indels + ' -x ' \
             + str(max_coverage)
    logging.debug('running %s%s', my_prog, my_arg)
    retcode = subprocess.call(my_prog + my_arg, shell=True)
    return retcode


def BH(p_vals, n):
    """performs Benjamini Hochberg procedure, returning q-vals'
       you can also see http://bit.ly/QkTflz
    """
    # p_vals contains the p-value and the index where it has been
    # found, necessary to assign the correct q-value
    q_vals_l = []
    prev_bh = 0
    for i, p in enumerate(p_vals):
        # Sometimes this correction can give values greater than 1,
        # so we set those values at 1
        bh = p[0] * n / (i + 1)
        bh = min(bh, 1)
        # To preserve monotonicity in the values, we take the
        # maximum of the previous value or this one, so that we
        # don't yield a value less than the previous.
        bh = max(bh, prev_bh)
        prev_bh = bh
        q_vals_l.append((bh, p[1]))
    return q_vals_l


def main(args):
    '''main code
    '''
    from Bio import SeqIO
    from math import log10
    import csv
    import inspect
    from datetime import date

    reference = args.f
    bam_file = args.b
    sigma = args.sigma
    increment = args.increment
    max_coverage = args.max_coverage
    ignore_indels = args.ignore_indels
    posterior_thresh = args.posterior_thresh

    logging.info(str(inspect.getfullargspec(main)))
    ref_m = dict([[s.id, str(s.seq).upper()]
                  for s in SeqIO.parse(reference, 'fasta')])

    # number of windows per segment
    segCov_m = segments(increment)
    logging.debug('coverage parsed')

    # snpD_m is the file with the 'consensus' SNVs (from different windows)
    logging.debug('now parsing SNVs')
    if not os.path.isfile('snv/SNV.txt'):
        snpD_m = getSNV(ref_m, segCov_m, increment, posterior_thresh)
        printRaw(snpD_m, increment)
    else:
        logging.debug('snv/SNV.txt found, moving to ./')
        shutil.move('snv/SNV.txt', './')

    d = ' -d' if ignore_indels else ''
    a = ' -a' if increment == 1 else ''
    # run strand bias filter, output in SNVs_%sigma.txt
    retcode_m = sb_filter(bam_file, sigma, amplimode=a, drop_indels=d,
                          max_coverage=max_coverage)
    if retcode_m != 0:
        logging.error('sb_filter exited with error %d', retcode_m)
        sys.exit()

    # parse the p values from SNVs*txt file
    snpFile = glob.glob('SNVs*.txt')[0]  # takes the first file only!!!
    write_list = []
    p_vals_m = []
    x = 0
    for s in open(snpFile):
        parts = s.rstrip().split('\t')
        p1 = parts[-1]
        p_vals_m.append((float(p1), x))
        write_list.append(s.rstrip().split('\t'))
        x += 1

    # sort p values, correct with Benjamini Hochberg and append to output
    p_vals_m.sort()
    q_vals = BH(p_vals_m, len(p_vals_m))
    for q, i3 in q_vals:
        write_list[i3].append(q)

    # Write ShoRAH csv output file
    if 'csv' in args.format:
        csv_file = '{}_final.csv'.format(os.path.splitext(snpFile)[0])
        if increment == 1:
            header_row = ['Chromosome', 'Pos', 'Ref', 'Var', 'Freq', 'Post',
                          'Fvar', 'Rvar', 'Ftot', 'Rtot', 'Pval', 'Qval']
        else:
            header_row = ['Chromosome', 'Pos', 'Ref', 'Var', 'Frq1', 'Frq2',
                          'Frq3', 'Pst1', 'Pst2', 'Pst3', 'Fvar', 'Rvar',
                          'Ftot', 'Rtot', 'Pval', 'Qval']
        with open(csv_file, 'w') as cf:
            writer = csv.writer(cf)
            writer.writerow(header_row)
            # only print when q >= 5%
            for wl in write_list:
                if wl[-1] >= 0.05:
                    writer.writerow(wl)

    # Write VCF output file
    if 'vcf' in args.format:
        VCF_file = f'{os.path.splitext(snpFile)[0]}_final.vcf'
        VCF_meta = [
            '##fileformat=VCFv4.2',
            f'##fileDate={date.today():%Y%m%d}',
            f'##source=ShoRAH_{args.version}',
            f'##reference={args.f}'
        ]
        for ref_name, ref_seq in ref_m.items():
            VCF_meta.append(f'##contig=<ID={ref_name},length={len(ref_seq)}>',)
        VCF_meta.extend([
            '##INFO=<ID=Fvar,Number=1,Type=Integer,Description="Number of forward reads with variant">',
            '##INFO=<ID=Rvar,Number=1,Type=Integer,Description="Number of reverse reads with variant">',
            '##INFO=<ID=Ftot,Number=1,Type=Integer,Description="Total number of forward reads">',
            '##INFO=<ID=Rtot,Number=1,Type=Integer,Description="Total number of reverse reads">',
            '##INFO=<ID=Pval,Number=1,Type=Float,Description="P-value for strand bias">',
            '##INFO=<ID=Qval,Number=1,Type=Float,Description="Q-value for strand bias">'
        ])

        if increment == 1:
            VCF_meta.extend([
                '##INFO=<ID=Freq<X>,Number=1,Type=Float,Description="Frequency of the variant">',
                '##INFO=<ID=Post<X>,Number=1,Type=Float,Description="Posterior probability of the variant">',
            ])
        else:
            VCF_meta.extend([
                '##INFO=<ID=Freq1,Number=1,Type=Float,Description="Frequency of the variant in window 1">',
                '##INFO=<ID=Freq2,Number=1,Type=Float,Description="Frequency of the variant in window 2">',
                '##INFO=<ID=Freq3,Number=1,Type=Float,Description="Frequency of the variant in window 3">',
                '##INFO=<ID=Post1,Number=1,Type=Float,Description="Posterior probability of the variant in window 1">',
                '##INFO=<ID=Post2,Number=1,Type=Float,Description="Posterior probability of the variant in window 2">',
                '##INFO=<ID=Post3,Number=1,Type=Float,Description="Posterior probability of the variant in window 3">',
            ])

        with open(VCF_file, 'w') as vcf:
            vcf.write('\n'.join(VCF_meta))
            # VCFv4.2 HEADER line
            vcf.write('\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO')
            # Iterate over single SNV lines and write them to output file
            for wl in write_list:
                # only print when q >= 5%
                if wl[-1] >= 0.05:
                    info = f'Fvar={wl[-6]};Rvar={wl[-5]};Ftot={wl[-4]};' \
                        f'Rtot={wl[-3]};Pval={wl[-2]};Qval={wl[-1]}'
                    if increment == 1:
                        post_avg = min([1, float(wl[5])])
                        info = f'Freq={wl[4]};Post={wl[5]};' + info
                    else:
                        freq_str = ';'.join([f'Freq{i+1}={j}'
                            for i, j in enumerate(wl[4:7]) if j != '*'])
                        post_str = ';'.join([f'Post{i+1}={j}'
                            for i, j in enumerate(wl[7:10]) if j != '*'])
                        info = f'{freq_str};{post_str};{info}'.replace('-', '0')
                        post_all = []
                        for freq, post in zip(wl[4:7], wl[7:10]):
                            if freq == '*':
                                pass
                            elif freq == '-':
                                post_all.append(0)
                            else:
                                post_all.append(min([1, float(post)]))
                        # Calculate posterior average
                        post_avg = sum(post_all) / len(post_all)
                    # Calculate a Phred quality score where the base calling
                    # error probabilities is set to (1 - posterior avg).
                    # Maximum is set to 100.
                    try:
                        qual_norm = -10 * log10(1 - post_avg)
                    except ValueError:
                        qual_norm = 100

                    vcf.write(f'\n{wl[0]}\t{wl[1]}\t.\t{wl[2]}\t{wl[3]}'
                              f'\t{qual_norm}\tPASS\t{info}')
