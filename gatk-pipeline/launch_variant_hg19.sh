#!/usr/bin/env bash
# John Vivian
#
# Please read the associated README.md before attempting to use.
#
# Precautionary step: Create location where jobStore and tmp files will exist
mkdir -p ${HOME}/toil_mnt
# Execution of pipeline
python exome_variant_pipeline.py \
${HOME}/toil_mnt/jstore \
--retryCount 1 \
--config "exome_variant_config.csv" \
--reference "https://s3-us-west-2.amazonaws.com/cgl-alignment-inputs/genome.fa" \
--phase "https://s3-us-west-2.amazonaws.com/cgl-variant-inputs/1000G_phase1.indels.hg19.sites.vcf" \
--mills "https://s3-us-west-2.amazonaws.com/cgl-variant-inputs/Mills_and_1000G_gold_standard.indels.hg19.sites.vcf" \
--dbsnp "https://s3-us-west-2.amazonaws.com/cgl-variant-inputs/dbsnp_138.hg19.vcf" \
--cosmic "https://s3-us-west-2.amazonaws.com/cgl-variant-inputs/cosmic.hg19.vcf" \
--output_dir ${HOME}/ \
--ssec ${HOME}/master.key \
--s3_dir 'cgl-driver-projects/wcdt/variants/' \
--workDir ${HOME}/toil_mnt \
--sudo \
#--restart