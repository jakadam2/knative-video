import os
import uuid
import subprocess

"""
Provides functions to split a video into fixed-length chunks, apply a filter
to each chunk, and merge the filtered chunks back into a single video file.

Dependencies:
- FFmpeg installed and available on PATH.
- Python 3.9+ (tested with 3.10).
- Standard library only (os, uuid, subprocess).

Usage example:
    result = process_entire_video("sample_vid.mp4", chunk_duration=15)
    print("✅ Finished. Filtered video saved at:", result)
"""

def split_video(input_path: str, output_dir: str, chunk_duration: int = 10):
    """
    Split a video into fixed-length segments by re-encoding with forced keyframes.

    Args:
        input_path (str): Path to the source video file.
        output_dir (str): Directory where chunks (e.g., chunk000.mp4, chunk001.mp4, …)
                          will be written. Created if it does not exist.
        chunk_duration (int): Desired length of each chunk, in seconds.

    """
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-i", input_path,
        # Force keyframes at every chunk_duration:
        "-force_key_frames", f"expr:gte(t,n_forced*{chunk_duration})",
        # Re-encode using libx264 with baseline profile + yuv420p pixel format:
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-profile:v", "baseline",      # baseline profile for maximum compatibility
        "-pix_fmt", "yuv420p",         # ensure pixel format is widely supported
        "-c:a", "aac",                 # re-encode audio to AAC for compatibility
        "-b:a", "128k",
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        f"{output_dir}/chunk%03d.mp4"
    ]
    subprocess.check_call(cmd)


def apply_filter(chunk_path: str, out_path: str):
    """
    Apply a “grayscale” filter. Reads chunk_path, writes filtered file to out_path.
    "-vf", "hue=s=0" can be changed to other ffmpeg filters

    Args:
        chunk_path (str): Path to the input chunk file.
        out_path (str): Path where the filtered output chunk will be written.
    """
    cmd = [
        "ffmpeg",
        "-i", chunk_path,
        "-vf", "hue=s=0",
        "-c:a", "copy",
        out_path
    ]
    subprocess.check_call(cmd)


def merge_chunks(filtered_dir: str, final_out: str):
    """
    Concatenate filtered chunks into a single video file.
    Look for files named *_filtered.mp4 in filtered_dir, sort them,
    write a filelist.txt, then concat them into final_out.

    Args:
        filtered_dir (str): Directory containing filtered chunks named *_filtered.mp4.
        final_out (str): Path where the final merged video will be written.
    """
    filelist_path = os.path.join(filtered_dir, "filelist.txt")
    with open(filelist_path, "w") as f:
        for fname in sorted(os.listdir(filtered_dir)):
            if fname.endswith("_filtered.mp4"):
                full = os.path.join(filtered_dir, fname)
                f.write(f"file '{full}'\n")

    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", filelist_path,
        "-c", "copy",
        final_out
    ]
    subprocess.check_call(cmd)


def process_entire_video(local_input: str, chunk_duration: int = 10):
    """
     High-level wrapper to:
      1. Split the input video into fixed-length chunks of length chunk_duration.
      2. Apply a predefined filter to each chunk.
      3. Merge the filtered chunks back into a single output video.

    Args:
        local_input (str): Path to the source video file.
        chunk_duration (int): Desired length of each chunk, in seconds.

    Returns:
        str: Path to the final merged video file.
    """
    unique_id = uuid.uuid4().hex
    # Directories for intermediate files for EKS/Knative
    chunk_dir = f"/tmp/chunks-{unique_id}"
    filtered_dir = f"/tmp/filtered-{unique_id}"
    final_out = f"/tmp/final-{unique_id}.mp4"

    # for local testing
    # chunk_dir = os.path.join(os.getcwd(), f"chunks-{unique_id}")
    # filtered_dir = os.path.join(os.getcwd(), f"filtered-{unique_id}")
    # final_out = os.path.join(os.getcwd(), f"final-{unique_id}.mp4")

    split_video(local_input, chunk_dir, chunk_duration)

    # apply filter
    os.makedirs(filtered_dir, exist_ok=True)
    for fname in sorted(os.listdir(chunk_dir)):
        if not fname.endswith(".mp4"):
            continue
        in_chunk = os.path.join(chunk_dir, fname)
        out_fname = fname.replace(".mp4", "_filtered.mp4")
        out_chunk = os.path.join(filtered_dir, out_fname)
        apply_filter(in_chunk, out_chunk)

    merge_chunks(filtered_dir, final_out)

    return final_out

if __name__ == "__main__":
    # Example usage: split sample_vid.mp4 into 15-second chunks,
    # apply grayscale filter, then merge back.
    result = process_entire_video("sample_vid.mp4", chunk_duration=15)
    print("✅ Finished. Filtered video saved at:", result)