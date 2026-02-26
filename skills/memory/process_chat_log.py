
import requests
import json
import time

archive_path = '/home/mikegg/.openclaw/workspace/imports/chat-archives/6cf22a6dd0f7b1f14c3678a4a3625e469a545aca871651f45425bd105d50514b-2026-02-17-00-42-25-7412e7141c2b4677ac6b1f0dc86dd871/conversations.json'
api_url = 'http://10.10.10.98:1234/api/v1/chat'
output_path = '/home/mikegg/.openclaw/workspace/memory/archive-summaries/profile-from-gpt-2026-02-23.md'
model_name = 'qwen2.5-32b-instruct'
# Adjusted context_length to be more conservative based on previous errors.
# LM Studio's API might have its own limits, and the model's max context length.
# For this test, let's stick to a lower value to avoid immediate truncation errors.
# The actual model context_length might be higher in LM Studio settings, 
# but API calls might enforce a certain limit.
configured_context_length = 4096  

try:
    with open(archive_path, 'r', encoding='utf-8') as f:
        all_data = json.load(f)
    
    # Initialize the output file with a header
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Mike (Beanz) Profile - Digested Archive\n\n")
        f.write("## Comprehensive Profile Summary\n\n")
        f.write("Processing chat logs in chunks to build a profile.\n\n")
        f.write("Date: 2026-02-23\n\n")

    aggregated_summary = ""
    current_chunk_index = 0
    
    print(f"Starting digestion of {len(all_data)} conversation entries with model: {model_name}")

    # Process conversation entries in chunks
    # Adjust chunk size based on typical token limits and API response times.
    # Example: process 20 conversations at a time.
    chunk_size = 20 
    num_chunks = (len(all_data) + chunk_size - 1) // chunk_size # Ceiling division

    for i in range(0, len(all_data), chunk_size):
        chunk_data = all_data[i : i + chunk_size]
        chunk_json_str = json.dumps(chunk_data)
        
        # Construct prompt for LM Studio
        prompt_content = (
            f"Analyze these chat logs (entries {i+1} to {min(i + chunk_size, len(all_data))}) and extract key details about the user (Mike/Beanz) regarding his technical setup, preferences, working style, and interests. "
            f"Append to the existing profile summary.\n\n"
            f"Existing Profile Summary:\n'''\n{aggregated_summary}\n'''\n\n"
            f"New JSON Data:\n'''json\n{chunk_json_str}\n'''"
        )

        payload = {
            "model": model_name,
            # Using the /api/v1/chat endpoint requires 'input' field
            "input": [{"type": "text", "content": prompt_content}], 
            "system_prompt": "As Arden's memory processor, build a profile of Mike (Beanz) from his chat logs. Focus on technical setup, preferences, WoW history, and personality. Be concise. Append to existing profile summary.",
            "context_length": configured_context_length, 
            "temperature": 0.3
        }

        print(f"Sending chunk {current_chunk_index + 1}/{num_chunks}...")
        
        try:
            response = requests.post(api_url, json=payload, timeout=180) # Increased timeout

            if response.status_code == 200:
                result_data = response.json()
                if 'output' in result_data and result_data['output']:
                    for output_item in result_data['output']:
                        if output_item['type'] == 'message':
                            current_chunk_summary = output_item['content']
                            aggregated_summary += current_chunk_summary + "\n\n"
                            print(f"Chunk {current_chunk_index + 1} processed.")
                        else:
                            print(f"Warning: Unexpected output type in response for chunk {current_chunk_index + 1}: {output_item.get('type')}")
                else:
                    print(f"Warning: No 'output' found in response for chunk {current_chunk_index + 1}.")
            else:
                print(f"LM_STUDIO_ERROR for chunk {current_chunk_index + 1}: {response.status_code} - {response.text}")
                # Decide how to proceed on error: break, retry, or log and continue
                break 

        except requests.exceptions.RequestException as e:
            print(f"ERROR: Connection to LM Studio failed for chunk {current_chunk_index + 1}: {e}")
            break 
        except Exception as e:
            print(f"An unexpected error occurred processing chunk {current_chunk_index + 1}: {str(e)}")
            break 
        
        current_chunk_index += 1
        time.sleep(2) # Slight delay

    # Write the final aggregated summary to the MD file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Mike (Beanz) Profile - Digested Archive\n\n")
        f.write("## Comprehensive Profile Summary\n\n")
        f.write(aggregated_summary)
        f.write("\n---\nEnd of digestion process.\n")
    
    print("DIGESTION_COMPLETE")

except FileNotFoundError:
    print("ERROR: conversations.json not found.")
except json.JSONDecodeError:
    print("ERROR: Could not decode JSON from conversations.json.")
except Exception as e:
    print(f"An error occurred during initial setup: {str(e)}")

