import src.calibration as calibrate
import src.filter_tools as filter
import src.plot_tools as plot
import src.math_tools as utils
import src.tree as tree
import cv2
import numpy as np
import argparse
import json
import os

from src.camera import Camera
from src.workspace import Environment


def main(exposure):

    # Calibration parameters
    targetDimensions = (6, 9)
    topThresh = 7
    shapeThresh = 15
    testStart = (355, 355)
    testEnd = (677, 677)
    pathStep = 0.075
    pathing = False

    # Get image from camera
    cam = Camera(exposure, targetDimensions)
    env = Environment()
    cam.hardware_white_balance()

    # Load camera parameters
    jsonFile = os.path.join(os.path.dirname(__file__), 'cameraData.json')
    print("LOADING CAMERA PARAMETERS FROM: ", jsonFile)
    with open(jsonFile, 'r') as fp:
        cam.calibrationParams = json.load(fp)

    #img = cam.stream(rectify=True)


    while True:
        #img = calibrate.remove_distortion(cam.calibrationParams, cam.get_img(), crop=False)
        img = cam.get_img()

        # Extract elements by colour
        env.shapeMask, shapes, tops = filter.get_shapes(img.copy(), cam.get_object_hues(), topThresh, shapeThresh)

        # Get the darkest largest object in the scene, usually the board. All board pixels must be connected!
        env.boardMask = filter.get_board(img)

        # worldMask is the largest component that includes shape pixels | board pixels
        #env.worldMask = filter.remove_components(env.shapeMask | env.boardMask, largest=True)

        # Remove pixels outside world
        #env.shapeMask = env.shapeMask & env.worldMask

        # Ensure that board pixels and shape pixels are mutually exclusive
        env.boardMask = env.boardMask & ~env.shapeMask
        env.boardMask = filter.remove_components(env.boardMask, largest=True)

        env.get_board_corners()
        for point in env.boardCorners:
            cv2.circle(img, point, 15, [0, 255, 0])

        cv2.circle(img, testStart, 10, [255, 0, 0])

        cv2.circle(img, testEnd, 10, [255, 0, 0])


        canvas = plot.show_mask(plot.show_mask(img, env.shapeMask, 1), env.boardMask, 2)
        if pathing:
            path = tree.generate_path(env.boardMask, testStart, testEnd, pathStep)
            if path is not None:
                canvas = plot.plot_path(canvas, path)
        # Create a
        #env.shapeMask = filter.get_shapes(img, env.worldMask ^ env.boardMask)
        #board = shapes ^ ~env.boardMask

        #edges = filter.infill_components(workSpace)

        #img = filter.get_edges(img, saturationThreshold)
        #img = filter.get_clahe(img)
        #saturationMask = filter.color_mask(img, saturationThreshold)

        #img = filter.remove_components()
        #cv2.imshow("Contours", plot.view_pair(env.boardMask, env.shapeMask))
        cv2.imshow("Contours", canvas)

        k = cv2.waitKey(1)
        if k == 115:    # Esc key to stop
            print("PATHING MODE ENGAGED")
            pathing = True
    exit(0)

    # Generate top-down view of image set
    cal.generate_overhead(cam, 200)

    # Show top-down view of dataset
    cv2.imshow('rectified',
               plot.view_set(calibrationTargets.rectified, (1280, 1024)))

    cv2.waitKey(0)


    ######################
    #                    #
    # PART B STARTS HERE #
    #                    #
    ######################

    # Assign image set to object
    obj = imageSet.__getattribute__(mode)

    if mode == 'skilled2':
        obj.images = [filter.trim_images(img) for img in obj.images]

    # Calculated edges
    obj.edges = [filter.get_edges(img) for img in obj.images]

    # Infill components
    obj.edges = [filter.infill_components(img) for img in obj.edges]

    # Close
    obj.edges = [cv2.morphologyEx(img, cv2.MORPH_CLOSE, np.ones((5, 5))) for img in obj.edges]

    # Remove small components
    obj.edges = [np.asarray(filter.remove_components(img, minSize=10000), dtype=np.uint8) for img in obj.edges]

    # Simple Canny edges
    obj.edges = [cv2.Canny(img, 40, 40, 20, L2gradient=True) for img in obj.edges]

    # Generate bouding boxes
    obj.boxes = [filter.get_boxes(edge) for edge in obj.edges]

    obj.imagesWithBoxes = [utils.draw_bounding_boxes(obj.images[i], obj.boxes[i]) for i in range(0, len(obj.images))]

    cv2.imshow('bounding boxes',
               plot.view_set(obj.imagesWithBoxes, (1280, 1024)))
    cv2.waitKey(0)


if __name__ == "__main__":

   parser = argparse.ArgumentParser(description="METR4202 imaging and pathing project Harry Roache-Wilson")
   parser.add_argument("exposure", type=int, help="Exposure value. High value is good for tight aperture, deep field")
   args = parser.parse_args()
   main(args.exposure)
