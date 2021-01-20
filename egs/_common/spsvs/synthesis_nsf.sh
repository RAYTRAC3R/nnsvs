# NOTE: the script is supposed to be used called from nnsvs recipes.
# Please don't try to run the shell script directry.

if [ -d conf/synthesis_nsf ]; then
    ext="--config-dir conf/synthesis_nsf"
else
    ext=""
fi

if [ -z $timelag_eval_checkpoint ]; then
    timelag_eval_checkpoint=best_loss.pth
fi
if [ -z $duration_eval_checkpoint ]; then
    duration_eval_checkpoint=best_loss.pth
fi
if [ -z $acoustic_eval_checkpoint ]; then
    acoustic_eval_checkpoint=latest.pth
fi

for s in ${testsets[@]}; do
    for input in label_phone_score label_phone_align; do
        if [ $input = label_phone_score ]; then
            ground_truth_duration=false
        else
            ground_truth_duration=true
        fi
	if [ -e $nsf_save_model_dir/eval_utt_length.dic ]; then
	    rm $nsf_save_model_dir/eval_utt_length.dic
	fi
        xrun nnsvs-synthesis-nsf $ext \
	     question_path=$question_path \
	     timelag=$timelag_synthesis \
             duration=$duration_synthesis \
             acoustic=$acoustic_synthesis \
             timelag.checkpoint=$expdir/timelag/$timelag_eval_checkpoint \
             timelag.in_scaler_path=$dump_norm_dir/in_timelag_scaler.joblib \
             timelag.out_scaler_path=$dump_norm_dir/out_timelag_scaler.joblib \
             timelag.model_yaml=$expdir/timelag/model.yaml \
             duration.checkpoint=$expdir/duration/$duration_eval_checkpoint \
             duration.in_scaler_path=$dump_norm_dir/in_duration_scaler.joblib \
             duration.out_scaler_path=$dump_norm_dir/out_duration_scaler.joblib \
             duration.model_yaml=$expdir/duration/model.yaml \
             acoustic.checkpoint=$expdir/acoustic/$acoustic_eval_checkpoint \
             acoustic.in_scaler_path=$dump_norm_dir/in_acoustic_scaler.joblib \
             acoustic.out_scaler_path=$dump_norm_dir/out_acoustic_scaler.joblib \
             acoustic.model_yaml=$expdir/acoustic/model.yaml \
	     nsf.config_yaml=$nsf_save_model_dir/config.yaml \
             utt_list=./data/list/$s.list \
             in_dir=data/acoustic/$input/ \
             out_dir=$expdir/synthesis/$s/latest/$input \
             ground_truth_duration=$ground_truth_duration
    done
done
