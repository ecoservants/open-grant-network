import os, logging

def setup_console_logger(name=__name__):
    """
    Centralized logging configuration to ensure consistent formats
    across all API endpoints.
    """
    logger = logging.getLogger(name)
    
    # Only add handler if it doesn't exist (prevents duplicate logs)
    if not logger.handlers:
        handler = logging.StreamHandler()
        # Format: Time - Module - Level - Message
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
    return logger


# Setup logger
def setup_file_logger(dirname, op_filename: str, name=__name__):
    os.makedirs(dirname, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers: 
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # File handler
        fh = logging.FileHandler(os.path.join(dirname, op_filename))
        fh.setLevel(logging.INFO)  # <-- INFO instead of ERROR
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
    return logger