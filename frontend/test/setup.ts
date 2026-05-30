import "@testing-library/jest-dom";

const createMemoryStorage = (): Storage => {
	let values = new Map<string, string>();
	return {
		get length() {
			return values.size;
		},
		clear: () => {
			values = new Map();
		},
		getItem: (key: string) => values.get(key) ?? null,
		key: (index: number) => Array.from(values.keys())[index] ?? null,
		removeItem: (key: string) => {
			values.delete(key);
		},
		setItem: (key: string, value: string) => {
			values.set(key, String(value));
		},
	};
};

const localStorageCandidate = globalThis.localStorage as Storage | undefined;
if (
	!localStorageCandidate ||
	typeof localStorageCandidate.clear !== "function" ||
	typeof localStorageCandidate.removeItem !== "function"
) {
	Object.defineProperty(globalThis, "localStorage", {
		value: createMemoryStorage(),
		configurable: true,
	});
}
