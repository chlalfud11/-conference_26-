cd '/Users/miryeong/0/08 졸업논문/start/conference-paper'
for pair in "exaone78:EXAONE-3.5-7.8B-Instruct-Q4_K_M.gguf" "kanana2_3b:kanana-2-3b-instruct.Q4_K_M.gguf" "seed15:hyperclovax-seed-text-instruct-1.5b-q4_k_m.gguf"; do
  tag=${pair%%:*}; f=${pair#*:}
  pkill -f "port 8080" ; sleep 3
  llama-server -m models/$f --host 127.0.0.1 --port 8080 -c 4096 -ngl 99 --jinja > logs/llama-bakeoff-$tag.log 2>&1 &
  for i in $(seq 1 180); do curl -sf http://127.0.0.1:8080/health >/dev/null && break; sleep 1; done
  python3 model_bakeoff.py run $tag > logs/bakeoff/$tag.out 2>&1 && echo "BK_OK $tag" || echo "BK_FAIL $tag $(tail -3 logs/bakeoff/$tag.out | tr '\n' ' ')"
done
echo BK_ALL_DONE