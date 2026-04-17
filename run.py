# satellite-scanner/run.py
import argparse
from scanner.pipeline import run_pipeline
from scanner.config import METRO_BBOX

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Microbasurales satellite scanner')
    parser.add_argument('--bbox', nargs=4, type=float, metavar=('W', 'S', 'E', 'N'),
                        default=METRO_BBOX,
                        help='Bounding box: west south east north')
    parser.add_argument('--output', default='data/output',
                        help='Output directory for seed files')
    args = parser.parse_args()
    run_pipeline(bbox=args.bbox, output_dir=args.output)
