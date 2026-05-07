import os
import json

def save_data(data, folder, filename, message=None):
    """
    Save data to a JSON file, creating directories if needed.

    Args:
        data (dict or list): The raw data to be saved.
        folder (str): Path to the folder where the JSON file will be stored.
        filename (str): The name of the file to save the data to.

    Returns:
        None

    Notes:
        - Creates the target directory if it does not exist.
        - Pretty-prints JSON with indentation for readability.
    """
    os.makedirs(folder, exist_ok=True)

    # Clean timestamp for filename
    file_path = os.path.join(folder, filename)

    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    if message is None:
        message = f"Saved {len(data)} records to {file_path}"

    print(f"{message}{file_path}")