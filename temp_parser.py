
    def _parse_histories(self, json_text: str) -> List[Dict[str, Any]]:
        """HTML内のエスケープ済みデータまたは純粋JSONから、株価履歴のみを厳選して抽出する"""
        histories = []
        
        # 1. 前処理: エスケープされた引用符 ( \") を通常の引用符 (") に置換
        norm_text = json_text.replace('\\"', '"')
        
        # 2. 株価データセクションのみをターゲットにする
        # 複数の "date":"..." "values":[...] のペアを抽出し、株価としての妥当性を1件ずつチェックする
        records = re.findall(r'\{"date":"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",\s*"values":\s*\[(.*?\}\s*\])', norm_text, re.S)
        
        for dt_str, val_block in records:
            # 内部の "value":"xxx" をすべて抽出
            vals = re.findall(r'"value":"([\d\.\-\,]+)"', val_block)
            
            # --- 厳格なバリデーション ---
            # A. 要素数チェック: 株価履歴は通常 [始値, 高値, 安値, 終値, 出来高] の5つ以上
            if len(vals) < 5:
                continue
                
            try:
                op_p = float(vals[0].replace(',', '')) # 始値
                hi_p = float(vals[1].replace(',', '')) # 高値
                lo_p = float(vals[2].replace(',', '')) # 安値
                cl_p = float(vals[3].replace(',', '')) # 終値
                vol  = float(vals[4].replace(',', '')) # 出来高
                
                # B. 株価としての妥当性チェック
                # 始値と終値があまりに乖離している（例：30%以上）場合は株価ではないとみなす
                if op_p <= 0 or cl_p <= 0:
                    continue
                if abs(op_p - cl_p) / op_p > 0.3:
                    continue
                
                # C. 極端な低価格(ゴミ)の除外
                if cl_p < 10.0:
                    continue
                
                h_item = {
                    "baseDatetime": dt_str, 
                    "closePrice": str(cl_p),
                    "volume": str(int(vol))
                }
                histories.append(h_item)
                
            except (ValueError, IndexError):
                continue

        # 3. 重複排除と日付順ソート
        unique_histories = {}
        for h in histories:
            dt_s = h['baseDatetime'].replace('-', '/')
            try:
                dt_obj = datetime.strptime(dt_s, '%Y/%m/%d')
                if dt_obj not in unique_histories:
                    unique_histories[dt_obj] = h
            except ValueError:
                continue

        sorted_keys = sorted(unique_histories.keys(), reverse=True)
        return [unique_histories[k] for k in sorted_keys]
