import src.math_tools as utils
import src.calibration as cal
import src.plot_tools as plot
import src.tree as tree
import src.filter_tools as filter
import cv2
import numpy as np
import math

class Prism(object):

    def __init__(self, top, topCent, side, sideCent):
        self.rows = top.shape[0]
        self.cols = top.shape[1]
        self.top = top
        self.topCentroid = topCent
        self.side = side
        self.sideCentoid = sideCent
        self.bottom = None
        self.bottomCentroid = None
        self.translationMatrix = None

    def generate_affine_transform(self, camPos, primitive):

        # Angle to camera from top-down perspective
        angleToCamera = math.atan2(camPos[1] - self.topCentroid[1], camPos[0] - self.topCentroid[0])

        # Translation amount for each step
        deltaX = primitive * math.cos(angleToCamera)
        deltaY = primitive * math.sin(angleToCamera)

        # Arbitrary points are chosen and then translated by deltaX and deltaY, so as to provide input required to
        # Generate affine transform matrix
        pts1 = np.float32([[50, 50], [200, 50], [50, 200]])
        pts2 = np.float32([[50 + deltaX, 50 + deltaY], [200 + deltaX, 50 + deltaY], [50 + deltaX, 200 + deltaY]])

        return cv2.getAffineTransform(pts1, pts2)

    def bootstrap_base(self, camPos, canvas):

        # We are going to shift the top face two pixels at a time (1mm) towards camera centre
        primitive = 2

        # Generate affine transform to shift face
        self.translationMatrix = self.generate_affine_transform(camPos, primitive)

        # Define the number of translation steps to move. Since each step is roughly 1mm, 100 translations = 10cm
        translationSteps = 100

        # Top face to shift
        shifted = self.top.copy()

        # Cost of each translation stored in cost array. Highest value in array corresponds to ideal translation length
        cost = []

        # Translate the top 100 times and store the number of white pixels after boolean and with sides.
        for _ in range(0, translationSteps):
            shifted = cv2.warpAffine(shifted, self.translationMatrix, (self.cols, self.rows))
            cost.append(np.sum((shifted & self.side) == 255))

        # Find optimal translation distance to translate top
        distance = cost.index(max(cost))

        # Overwrite translation matrix with optimal translation distance
        self.translationMatrix = self.generate_affine_transform(camPos, 2 * distance)

        # Project top face onto bottom face :)
        self.bottom = cv2.warpAffine(self.top.copy(), self.translationMatrix, (self.cols, self.rows))


class Environment(object):

    def __init__(self, canvas, worldCorners):


        # Environment variables
        self.worldCorners = worldCorners
        self.canvas = canvas            # Canvas of environment used to plot objects
        self.boardMask = None           # Board mask generated from black pixels
        self.boardMaskFilled = None     # Board mask generated from detected corners
        self.boardCorners = []          # Board corners

        # Data pertaining objects in environment
        self.tops = None                # Combined tops for all foam objects
        self.sides = None               # Combined sides for all foam objects
        self.shapes = []                # List of numpy arrays that contain both top and side information for each obj
        self.cards = None
        self.goals = None               # Combined goals
        self.prisms = []                # List of prism objects, one for each foam block

        # Camera and frame data
        self.wsOrigin = None            # Origin of workspace frame
        self.rvecs = None               # Rotation matrix between workspace and camera
        self.tvecs = None               # Translation matrix between workspace and camera
        self.mtx = None                 # Camera matrix
        self.dist = None                # Camera distortion coefficients

        # Path planning and goal data
        self.startPts = []
        self.goalPts = []
        self.paths = []
        self.workspace = None
        self.dilatedWorkspace = None
        self.matFile = {}

    def show_canvas(self):

        # Render tops and sides on workspace
        cv2.imshow("canvas", plot.show_mask(plot.show_mask(
            plot.show_mask(self.canvas, self.workspace, 2), self.tops, 1, opacity=0.5), self.sides, 0, opacity=0.5))


    def get_paths(self, pathStep):

        print("PATHING MODE ENGAGED")
        print(self.startPts, self.goalPts)
        if len(self.startPts) == len(self.goalPts):

            paths = []

            # Find path for each start-goal pair
            for traj in range(0, len(self.startPts)):

                # Prepare start/end points by reversing indices
                startReversed = (self.startPts[traj][1], self.startPts[traj][0])
                endReversed = (self.goalPts[traj][1], self.goalPts[traj][0])

                # Find path
                path = tree.generate_path(self.dilatedWorkspace, startReversed, endReversed, pathStep)
                if path is not None:
                    self.canvas = plot.plot_path(self.canvas, path)
                    paths.append(path)
                    cv2.imshow("canvas", plot.show_mask(plot.show_mask(plot.show_mask(
                        self.canvas, self.workspace, 2), self.tops, 1, opacity=0.5), self.sides, 0, opacity=0.5))

            if len(paths) == max(len(self.startPts), len(self.goalPts)):
                self.paths = paths
                return True

        print("PATHING FAILED. ADJUST WORLD AND TRY AGAIN")
        return False


    def generate_workspace(self):

        mask = self.boardMaskFilled.copy()

        for prism in self.prisms:
            mask = (mask | prism.top | prism.side) & ~prism.bottom

        self.workspace = mask & ~self.cards

    def get_prisms(self):
        # Store prisms in dummy array before returning them
        prisms = []

        # Generate top-side pairs for each top.
        for [top, side] in self.shapes:
            tops = filter.separate_components(top)
            sides = filter.separate_components(side)

            if len(tops) == len(sides):

                # Instantiate prism object with a top, top centroid, side and side centroid
                for i in range(0, len(tops)):
                    prisms.append(Prism(tops[i][0], tops[i][1], sides[i][0], sides[i][1]))
            else:
                print('topside error! Number of tops != number of sides, dammit')
        self.prisms = prisms

    def get_start_and_end_points(self):

        # Count number of goals
        num, output, stats, centroids = cv2.connectedComponentsWithStats(self.goals, connectivity=8)

        # Kernel for dilating workspace once start points have been removed
        kernel = np.ones((5, 5), dtype=np.uint8)

        for component in range(1, num):

            # Get goal and appropriate start location
            goalPt = (int(centroids[component][0]), int(centroids[component][1]))
            self.goalPts.append(goalPt)
            cv2.circle(self.canvas, goalPt, 40, (0, 255, 0), 2)

            # Find corresponding start location
            startCandidate = filter.get_circle(~self.workspace, 37, 40)

            if startCandidate is not None:

                # Add circle to image
                self.startPts.append((startCandidate[0], startCandidate[1]))

                # Plot circle on image
                cv2.circle(self.canvas, (startCandidate[0], startCandidate[1]), startCandidate[2], (0, 255, 0), 2)

                # Once start location is found on workspace, floodfill location so path planner can access it
                cv2.floodFill(self.workspace, None, self.startPts[-1], 255)

        self.dilatedWorkspace = ~cv2.dilate(~cv2.morphologyEx(self.workspace,
                                                              cv2.MORPH_CLOSE, kernel), kernel, iterations=10)

    def get_ws_objects(self, image, hues, bThresh, wThresh, hThresh, sThresh, vThresh):
        image = cv2.bilateralFilter(image, 9, 40, 40)
        gray = ~cv2.cvtColor(filter.get_clahe(image), cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image.copy(), cv2.COLOR_BGR2HSV)
        kernel = np.ones((5, 5), np.uint8)
        self.tops = np.zeros(gray.shape, dtype=np.uint8)
        self.sides = np.zeros(gray.shape, dtype=np.uint8)

        for hue in hues:

            # Segment top of coloured object with hue in hues
            top = cv2.inRange(hsv,
                              (max(hue[0] - hThresh, 0),
                               max(hue[1] - sThresh, 0),
                               max(hue[2] - vThresh, 0)),
                              (min(hue[0] + hThresh, 180),
                               max(hue[1] + sThresh, 255),
                               max(hue[2] + vThresh, 255)))

            # Segment entirety of coloured object with hue in hues
            side = cv2.inRange(hsv,
                               (max(hue[0] - int(1.0 * hThresh), 0), 50, 50),
                               (min(hue[0] + int(1.0 * hThresh), 180), 255, 255))

            # Add tops and sides to cumulative masks, append individual shape data to array for each hue
            self.tops = self.tops | top
            self.sides = self.sides | side
            self.shapes.append([top, side])

        # Segment goal objects from image
        self.goals = cv2.morphologyEx(np.asarray((gray < wThresh) * 255, dtype=np.uint8) & ~self.tops, cv2.MORPH_CLOSE,
                                      kernel, iterations=2)

        # Get card backs (purple colour)
        self.cards = cv2.dilate(filter.infill_components(self.shapes[-1][0] | self.shapes[-1][1])
                                | self.shapes[-1][0] | self.shapes[-1][1], kernel)

        # Get card fronts (white colour)
        self.cards = self.cards | cv2.dilate(filter.remove_components(
            cv2.dilate(cv2.dilate(
                self.goals.copy(), kernel, iterations=2), kernel, iterations=1) | self.goals, minSize=10000), kernel,
            iterations=1)

        # Update goals to remove white card faces and small sections of goal
        self.goals = filter.remove_components(self.goals & ~self.cards, minSize=2500)

        # Delete cards from shapes. We only want '3d' objects in this list
        del self.shapes[-1]

        # Segment board from image
        self.boardMask = (cv2.inRange(hsv, (0, 0, 0), (180, bThresh, bThresh)) |
                          np.asarray((gray > 220) * 255, dtype=np.uint8)) & ~self.cards

        # Close board mask
        self.boardMask = cv2.morphologyEx(self.boardMask, cv2.MORPH_CLOSE, np.ones((10, 10), np.uint8))

    def update_masks(self):

        # Instantiate morphology kernel
        kernel = np.ones((6, 6), np.uint8)

        # Draw polygon between workspace corners
        pts = np.array(self.boardCorners, np.int32).reshape((-1, 1, 2))
        self.boardMaskFilled = cv2.fillPoly(np.zeros(self.boardMask.shape, dtype=np.uint8), [pts], 255)

        # Close masks and remove small objects
        self.tops = filter.remove_components(cv2.morphologyEx(self.tops, cv2.MORPH_CLOSE, kernel), minSize=2000) & \
                    ~self.cards
        self.sides = filter.remove_components(cv2.morphologyEx(self.sides, cv2.MORPH_CLOSE, kernel), minSize=2500) & \
                     ~self.cards

        # Clean up masks by removing intersections
        self.sides = ((self.sides & ~self.tops) & self.boardMaskFilled) & ~self.boardMask & ~self.cards
        self.tops = (self.tops & ~self.sides) & self.boardMaskFilled & ~self.cards
        self.goals = filter.remove_components(self.goals & self.boardMaskFilled, minSize=2000)
        self.shapes = [[filter.remove_components(cv2.morphologyEx(top & self.tops,
                                                                  cv2.MORPH_CLOSE, kernel), minSize=2000),
                        filter.remove_components(cv2.morphologyEx(side & self.sides, cv2.MORPH_CLOSE, kernel),
                                                 minSize=1800)] for [top, side] in self.shapes]

    def get_ws_frame(self, mtx, dist):

        # Check if workspace is tilted by calculating angle between top line and side line
        topLine = math.atan2(self.boardCorners[1][0] - self.boardCorners[1][1], self.boardCorners[0][0] - self.boardCorners[1][0])
        sideLine = math.atan2(self.boardCorners[1][0] - self.boardCorners[3][1], self.boardCorners[0][0] - self.boardCorners[3][0])
        self.matFile['tilted'] = False

        if (topLine - sideLine) % math.pi < 0.62: # Tilted

            self.matFile['tilted'] = True

            # Workspace corners in workspace frame [0, 1]
            objp = np.zeros((4, 3), np.float32)
            objp[:, :2] = np.mgrid[0:2, 0:2].T.reshape(-1, 2)

            # SolvePnPRansac wants a very specific matrix dimension for corners. Manipulate corner matrix to conform.
            # Specifically, it is expecting a square with same dimensions as checkerboard square. Since we know board
            # dimensions, we can generate such a square on which our origin lays. Then it must be manipulated so that
            # it conforms to the pedantic cv2 specification. To be fair, it because cv2 is so well optimised.
            self.wsOrigin = cal.generate_origin_square(self.boardCorners)
            numpyCorners = np.expand_dims(np.asarray([np.asarray(cnr, dtype=np.float32).T for cnr in self.wsOrigin]),
                                          axis=1)

            # Generate rotation and translation vectors for calibration target
            _, rvecs, tvecs, inliers = cv2.solvePnPRansac(objp, numpyCorners, mtx, dist)
            self.matFile['rvecs'] = rvecs
            self.matFile['tvecs'] = tvecs

            try:
                self.canvas = plot.render_origin_frame(self.canvas, numpyCorners, rvecs, tvecs, mtx, dist)
                self.rvecs = rvecs
                self.tvecs = tvecs
                self.mtx = mtx
                self.dist = dist
            except OverflowError:
                print('No line to draw')

    def fill_board(self):

        # Prepare filled image of board (i.e. fill shape gaps). Don't overwrite board.
        self.boardFilled = self.boardMask.copy()

        # Mask used to flood filling. Notice the size needs to be 2 pixels than the image.
        h, w = self.boardMask.shape[:2]
        mask = np.zeros((h + 2, w + 2), np.uint8)

        # Floodfill from point (0, 0)
        cv2.floodFill(self.boardFilled, mask, (0, 0), 255)

        # Combine the two images to get the foreground.
        self.boardFilled = self.boardMask | cv2.bitwise_not(self.boardFilled)

    def get_board_corners(self):

        rotated = utils.rotate_image(self.boardMask)
        h, w = rotated.shape

        try:
            t, b = np.array(np.where(rotated == 255))[:, [0, -1]].T
            l, r = np.array(np.where(np.rot90(rotated) == 255))[:, [0, -1]].T

            rotatedCorners = [tuple(reversed(t)), tuple(reversed(b)),
                              tuple([w - l[0], l[1]]), tuple([w - r[0], r[1]])]

            unrotatedVectors = [(math.hypot(1155.0 - cnr[0], cnr[1] - 667.0),
                               math.atan2(667.0 - cnr[1], 1155.0 - cnr[0]) - math.pi / 4) for cnr in rotatedCorners]
            self.boardCorners = [(578 + int(vect[0] * math.sin(vect[1])),
                                  334 - int(vect[0] * math.cos(vect[1]))) for vect in unrotatedVectors]

            self.boardCorners = [self.boardCorners[3], self.boardCorners[0], self.boardCorners[2], self.boardCorners[1]]


        except IndexError:
           print('Not enough board pixels to get corners')

        # Ensure that main loop restarts if four corners aren't found
        if len(self.boardCorners) is 4:
            return True
        else:
            return False
