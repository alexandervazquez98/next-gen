import React from "react";

import {
	getCategoryIconEntry,
	resolveCategoryIconKey,
	type CategoryIconEntry,
	type ResolveCategoryIconArgs,
} from "../utils/categoryIcons";

export interface CategoryIconProps extends ResolveCategoryIconArgs {
	className?: string;
	iconClassName?: string;
}

const buildTitle = (entry: CategoryIconEntry): string => `${entry.label} technology icon`;

export const CategoryIcon: React.FC<CategoryIconProps> = ({
	iconKey,
	categoryName,
	className,
	iconClassName,
}) => {
	const resolvedKey = resolveCategoryIconKey({ iconKey, categoryName });
	const entry = getCategoryIconEntry(resolvedKey);

	return (
		<span
			role="img"
			aria-label={buildTitle(entry)}
			className={`material-symbols-outlined ${className ?? "text-[1.25rem]"} ${iconClassName ?? ""}`.trim()}
			title={buildTitle(entry)}
		>
			{entry.materialSymbol}
		</span>
	);
};

export default CategoryIcon;
