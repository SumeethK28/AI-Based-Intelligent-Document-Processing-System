import cv2
import numpy as np

class ImagePreprocessor:
    def preprocess(self, image: np.ndarray, grayscale: bool = True, enhance_contrast: bool = False, denoise: bool = False, threshold: bool = False) -> np.ndarray:
        processed = image.copy()

        if image is None or image.size == 0:
            raise ValueError("Cannot preprocess an empty image.")

        if grayscale:
            processed = self.to_grayscale(processed)

        if enhance_contrast:
            processed = self.enhance_contrast(processed)

        if denoise:
            processed = self.denoise(processed)

        if threshold:
            processed = self.apply_threshold(processed)

    def to_grayscale(self, image: np.ndarray) -> np.ndarray:

        if len(image.shape) == 2:
            return image.copy()

        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def enhance_contrast(self, image: np.ndarray) -> np.ndarray:

        gray = self.to_grayscale(image)

        return cv2.equalizeHist(gray)

    def denoise(self, image: np.ndarray) -> np.ndarray:

        gray = self.to_grayscale(image)

        return cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

    def apply_threshold(self, image: np.ndarray) -> np.ndarray:

        gray = self.to_grayscale(image)

        _, thresholded = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        return thresholded