/**
 * gradient-util
 */
import { Options, ValidateGradientLine, ValidateColorStops } from '../typedef';
/**
 * get gradient type
 * @param value - gradient value
 * @returns gradient type
 */
export declare const getGradientType: (value: string) => string;
/**
 * validate linear-gradient line
 * @param value - line value
 * @returns result
 */
export declare const validateLinearGradientLine: (value: string) => ValidateGradientLine;
/**
 * validate radial-gradient line
 * @param value - line value
 * @returns result
 */
export declare const validateRadialGradientLine: (value: string) => ValidateGradientLine;
/**
 * validate conic-gradient line
 * @param value - line value
 * @returns result
 */
export declare const validateConicGradientLine: (value: string) => ValidateGradientLine;
/**
 * validate gradient line
 * @param value - gradient line value
 * @param type - gradient type
 * @returns result
 */
export declare const validateGradientLine: (value: string, type: string) => ValidateGradientLine;
/**
 * validate color stop list
 * @param list
 * @param type
 * @param [opt]
 * @returns result
 */
export declare const validateColorStopList: (list: string[], type: string, opt?: Options) => ValidateColorStops;
