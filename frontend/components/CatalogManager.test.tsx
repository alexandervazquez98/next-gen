import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import CatalogManager from './CatalogManager';

type MockCategory = {
	name: string;
	icon_key?: string | null;
};

type MockHardware = {
	brand: string;
	model: string;
	category?: string;
	owner?: string;
};

type MockOwner = {
	name: string;
	users: [];
};

const mocks = vi.hoisted(() => ({
	mockApiGet: vi.fn(),
	mockApiPost: vi.fn(),
	mockApiPut: vi.fn(),
	mockApiDelete: vi.fn(),
}));

vi.mock('../services/api', () => ({
	api: {
		get: mocks.mockApiGet,
		post: mocks.mockApiPost,
		put: mocks.mockApiPut,
		delete: mocks.mockApiDelete,
	},
}));

const hardware: MockHardware[] = [];
const owners: MockOwner[] = [];

const categories: MockCategory[] = [
	{ name: 'Layer 2 switch', icon_key: 'switch_l2' },
	{ name: 'Video Analytics' },
];

const openCategoryEditor = async (name: string) => {
	fireEvent.click(screen.getByRole('button', { name: 'CATEGORIES' }));

	await waitFor(() => {
		expect(screen.getByText(name)).toBeInTheDocument();
	});

	const editButton = screen.getByRole('button', { name: `edit category ${name}` });
	fireEvent.click(editButton);
	await waitFor(() => {
		expect(screen.getByRole('heading', { name: /^Edit/i })).toBeInTheDocument();
	});
};

const withinCategoryEditor = () => {
	const editorPanel = screen.getByRole('heading', { name: /^(Edit|New)/i }).parentElement;
	if (!editorPanel) {
		throw new Error('Category editor panel not found');
	}

	return within(editorPanel);
};

describe('CatalogManager category icon selector', () => {
	beforeEach(() => {
		mocks.mockApiGet.mockReset();
		mocks.mockApiPost.mockReset();
		mocks.mockApiPut.mockReset();
		mocks.mockApiDelete.mockReset();

		mocks.mockApiGet.mockImplementation(async (endpoint: string) => {
			if (endpoint === '/hardware') return hardware;
			if (endpoint === '/categories') return categories;
			if (endpoint === '/owners') return owners;
			return Promise.resolve([]);
		});

		mocks.mockApiPut.mockResolvedValue(undefined);
		mocks.mockApiPost.mockResolvedValue(undefined);
		mocks.mockApiDelete.mockResolvedValue(undefined);
	});

	it('shows the current selected icon while editing a category', async () => {
		render(<CatalogManager />);

		await openCategoryEditor('Layer 2 switch');

		const editor = withinCategoryEditor();
		expect(editor.getAllByRole('img', { name: /layer 2 switch technology icon/i }).length).toBeGreaterThan(0);
		expect(editor.getByRole('textbox', { name: /search icons/i })).toHaveValue('');
	});

	it('searches the icon catalog, updates the preview, and saves the selection', async () => {
		render(<CatalogManager />);

		await openCategoryEditor('Layer 2 switch');

		const searchInput = screen.getByRole('textbox', { name: /search icons/i });
		fireEvent.change(searchInput, { target: { value: 'router' } });

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /select router icon/i })).toBeInTheDocument();
			expect(screen.queryByRole('button', { name: /select layer 2 switch icon/i })).not.toBeInTheDocument();
		});

		fireEvent.click(screen.getByRole('button', { name: /select router icon/i }));
		const editor = withinCategoryEditor();
		expect(editor.getAllByRole('img', { name: /router technology icon/i }).length).toBeGreaterThan(0);

		fireEvent.click(screen.getByRole('button', { name: /save/i }));

		await waitFor(() => {
			expect(mocks.mockApiPut).toHaveBeenCalledWith('/categories/Layer 2 switch', {
				name: 'Layer 2 switch',
				icon_key: 'router',
			});
		});
	});

	it('allows selecting the generic icon and sends the generic key', async () => {
		render(<CatalogManager />);

		await openCategoryEditor('Video Analytics');

		fireEvent.click(screen.getByRole('button', { name: /select generic icon/i }));
		const editor = withinCategoryEditor();
		expect(editor.getAllByRole('img', { name: /generic technology icon/i }).length).toBeGreaterThan(0);

		fireEvent.click(screen.getByRole('button', { name: /save/i }));

		await waitFor(() => {
			expect(mocks.mockApiPut).toHaveBeenCalledWith('/categories/Video Analytics', {
				name: 'Video Analytics',
				icon_key: 'generic',
			});
		});
	});

	it('keeps icon selector state scoped to the active edit session', async () => {
		render(<CatalogManager />);

		await openCategoryEditor('Layer 2 switch');
		fireEvent.click(screen.getByRole('button', { name: /select router icon/i }));
		fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

		fireEvent.click(screen.getByRole('button', { name: /add/i }));

		await waitFor(() => {
			expect(screen.getByRole('heading', { name: /new/i })).toBeInTheDocument();
		});

		const editor = withinCategoryEditor();
		expect(editor.getByRole('textbox', { name: /search icons/i })).toHaveValue('');
		expect(editor.getAllByRole('img', { name: /generic technology icon/i }).length).toBeGreaterThan(0);
	});
});
