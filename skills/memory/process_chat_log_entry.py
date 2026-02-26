
import requests
import json
import time

archive_path = '/home/mikegg/.openclaw/workspace/imports/chat-archives/6cf22a6dd0f7b1f14c3678a4a3625e469a545aca871651f45425bd105d50514b-2026-02-17-00-42-25-7412e7141c2b4677ac6b1f0dc86dd871/conversations.json'
api_url = 'http://10.10.10.98:1234/api/v1/chat'
output_path = '/home/mikegg/.openclaw/workspace/memory/archive-summaries/profile-from-gpt-2026-02-23.md'
model_name = 'qwen2.5-32b-instruct'
# Even with chunk_size=1, the n_keep might be high. 
# Using a higher context_length if the model/hardware supports it.
configured_context_length = 32768 

try:
    with open(archive_path, 'r', encoding='utf-8') as f:
        all_data = json.load(f)
    
    # Initialize the output file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Mike (Beanz) Profile - Digested Archive\n\n")
        f.write("## Initial Summary (one-by-one entry processing)...\n\n")
        f.write(f"Processing {len(all_data)} conversation entries individually.\n\n")
        f.write("Date: 2026-02-23\n\n")

    aggregated_summary = ""
    current_entry_index = 0
    
    print(f"Starting digestion of {len(all_data)} conversation entries with model: {model_name}")

    # Process conversation entries individually
    for i, entry_data in enumerate(all_data):
        entry_json_str = json.dumps(entry_data)
        
        # Construct prompt for LM Studio
        prompt_content = (
            f"Analyze this single chat log entry (entry {i+1} of {len(all_data)}) and extract key details about Mike (Beanz) regarding his technical setup, preferences, working style, or interests. "
            f"Be extremely concise. If nothing significant is found, reply WITH NO OUTPUT. Append to existing profile summary if you have information.\n\n"
            f"Existing Profile Summary:\n'''\n{aggregated_summary}\n'''\n\n"
            f"New Entry JSON:\n'''json\n{entry_json_str}\n'''"
        )

        payload = {
            "model": model_name,
            "input": [{"type": "text", "content": prompt_content}], 
            "system_prompt": "You are Arden's memory processor. Extract key profile points about Mike from his chat logs. Be very concise or say nothing.",
            "context_length": configured_context_length, 
            "temperature": 0
        }

        print(f"Processing entry {i+1}/{len(all_data)}...")
        
        try:
            response = requests.post(api_url, json=payload, timeout=60) 

            if response.status_code == 200:
                result_data = response.json()
                if 'output' in result_data and result_data['output']:
                    for output_item in result_data['output']:
                        if output_item['type'] == 'message':
                            current_entry_summary = output_item['content'].strip()
                            if current_entry_summary and "NO OUTPUT" not in current_entry_summary:
                                aggregated_summary += current_entry_summary + "\n"
                                print(f"Entry {i+1} summary added.")
                            else:
                                print(f"Entry {i+1} - No significant content found.")
                        else:
                            print(f"Unexpected output type: {output_item['type']}")
                else:
                    print(f"Warning: No 'output' found for entry {i+1}.")
            else:
                print(f"LM_STUDIO_ERROR for entry {i+1}: {response.status_code} - {response.text}")
                # For individual processing, logging and continuing might be better than breaking. 
                continue 

        except requests.exceptions.RequestException as e:
            print(f"ERROR: Connection failure for entry {i+1}: {e}")
            break 
        except Exception as e:
            print(f"Error processing entry {i+1}: {str(e)}")
            continue 
        
        # Periodic saves to the file so progress isn't lost
        if (i + 1) % 10 == 0:
            with open(output_path, 'a', encoding='utf-8') as f:
                f.write(f"\n### Progress Update (Entry {i+1})\n\n{aggregated_summary}\n")
            print(f"Saved progress at entry {i+1}.")

        time.sleep(1) # Small delay

    # Final write
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Mike (Beanz) Profile - Digested Archive\n\n")
        f.write("## Comprehensive Profile Summary\n\n")
        f.write(aggregated_summary)
        f.write("\n---\nEnd of digestion process.\n")
    
    print("DIGESTION_COMPLETE")

except Exception as e:
    print(f"An error occurred during initial setup: {str(e)}")

PY
