import numpy as np
from scipy.optimize import curve_fit


class FittingModel:
    def __init__(self):
        self.params = np.array([])

    def fit(
        self,
        x_data: np.array,
        y_data: np.array,
        sigma: list | None = None,
    ):
        self.params, _ = curve_fit(
            self._fitting_func,
            x_data,
            y_data,
            p0=[1, 1],
            bounds=([0, 0], [np.inf, 1]),
            sigma=sigma,
        )

    def predict(self, x_fit: np.array):
        y_fit = self._fitting_func(x_fit, *self.params)
        return y_fit

    def get_hovertext(self) -> str:
        return (
            # "近似式 <i>y</i> = a b <sup><i>x</i></sup> + c"
            f"近似式 <i>y</i> = <i>Σ<sub>k</sub><sup>x</sup></i> "
            f"¥{self.params[0]:,.0f} (1 + {self.params[1]:.4f}) <sup><i>k</i></sup>"
            f"<br>  (年換算利回り {self.params[1]*100*12:+.2f}%)"
        )

    def _fitting_func(self, x: np.array, *params) -> np.ndarray:
        return self._fitting_func2(x, *params)

    def _fitting_func1(
        self, x: np.array, a: float, b: float, c: float = 0
    ) -> np.ndarray:
        """
        指数近似のフィッティング関数
          近似式 y = a (b) ^x + c
        """
        return a * ((1 + b) ** x) + c

    def _fitting_func2(self, x: np.array, a: float, b: float) -> np.ndarray:
        """
        指数近似のフィッティング関数
          近似式 y = Σ_k^x a (1 + b) ^k
        x: 月単位の時間軸
        a: 毎月積立投資額
        b: 月利
        """
        return a * ((1 + b) ** x - 1) / b
