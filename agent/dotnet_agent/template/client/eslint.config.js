import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

const noEmptySelectValue = {
  meta: {
    type: 'problem',
    docs: {
      description: 'Disallow empty string values in Select item components',
    },
    messages: {
      emptySelectValue: 'Select item components cannot have an empty string as value. Use a meaningful default value.',
    },
  },
  create(context) {
    return {
      JSXAttribute(node) {
        if (
          node.name?.name === 'value' &&
          node.value?.type === 'Literal' &&
          node.value.value === ''
        ) {
          // Check if parent is likely a Select item component
          const parentName = node.parent?.name?.name;
          if (parentName && (
            // Core select patterns
            parentName.includes('Select') ||
            parentName.includes('Option') ||
            // These are the most likely to be used with DB data
            parentName === 'MenuItem' ||
            parentName === 'DropdownMenuItem' ||
            parentName === 'RadioGroupItem'
          )) {
            context.report({
              node,
              messageId: 'emptySelectValue',
            });
          }
        }
      },
    };
  },
};

const noEmptyDynamicSelectValue = {
  meta: {
    type: 'problem',
    docs: {
      description: 'Warn about potentially empty dynamic values in Select components',
    },
    messages: {
      potentiallyEmptyValue: 'This value might be empty when data is not loaded. Consider using a fallback',
    },
  },
  create(context) {
    return {
      JSXAttribute(node) {
        if (
          node.name?.name === 'value' &&
          node.value?.type === 'JSXExpressionContainer'
        ) {
          const parentName = node.parent?.name?.name;
          if (parentName && (
            parentName.includes('Select') ||
            parentName.includes('Option') ||
            parentName === 'MenuItem' ||
            parentName === 'DropdownMenuItem' ||
            parentName === 'RadioGroupItem'
          )) {
            const expr = node.value.expression;

            // Skip if it's already a logical expression with fallback
            if (expr.type === 'LogicalExpression' &&
                (expr.operator === '||' || expr.operator === '??')) {
              return;
            }

            // Skip if it's a conditional expression (ternary)
            if (expr.type === 'ConditionalExpression') {
              return;
            }

            // Only check member expressions (like user.id, item.value)
            if (expr.type !== 'MemberExpression') {
              return;
            }

            // Skip if we're inside a map/filter/forEach callback (likely iterating over existing data)
            let parent = node;
            while (parent) {
              if (parent.type === 'CallExpression' &&
                  parent.callee?.property?.name &&
                  ['map', 'filter', 'forEach', 'reduce'].includes(parent.callee.property.name)) {
                return;
              }
              parent = parent.parent;
            }

            // Check if there's a parent conditional that ensures the value exists
            let ancestor = node.parent;
            while (ancestor) {
              // If we're inside an if statement or conditional that checks this value
              if (ancestor.type === 'IfStatement' || ancestor.type === 'ConditionalExpression') {
                return; // Assume it's been validated
              }
              ancestor = ancestor.parent;
            }

            context.report({
              node,
              messageId: 'potentiallyEmptyValue',
            });
          }
        }
      },
    };
  },
};

const noMockData = {
  meta: {
    type: 'problem',
    docs: {
      description: 'Disallow mock data and mock implementations',
    },
    messages: {
      mockVariableName: 'Variable names containing "mock", "dummy", or "fake" are not allowed. Use real data.',
      mockComment: 'Comments mentioning mock/dummy/fake data are not allowed. Implement real functionality.',
    },
  },
  create(context) {
    return {
      // Check variable and function names
      Identifier(node) {
        const name = node.name.toLowerCase();
        if ((name.includes('mock') || name.includes('dummy') || name.includes('fake')) &&
            (node.parent.type === 'VariableDeclarator' ||
             node.parent.type === 'FunctionDeclaration' ||
             node.parent.type === 'FunctionExpression')) {
          context.report({
            node,
            messageId: 'mockVariableName',
          });
        }
      },
      // Check comments
      Program() {
        const sourceCode = context.getSourceCode();
        const comments = sourceCode.getAllComments();

        comments.forEach(comment => {
          const text = comment.value.toLowerCase();
          if (text.includes('mock') || text.includes('dummy') || text.includes('fake')) {
            context.report({
              loc: comment.loc,
              messageId: 'mockComment',
            });
          }
        });
      },
    };
  },
};

export default tseslint.config(
  { ignores: ['dist', '.cursor/**/*'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'custom': {
        rules: {
          'no-empty-select-value': noEmptySelectValue,
          'no-empty-dynamic-select-value': noEmptyDynamicSelectValue,
          'no-mock-data': noMockData,
        },
      },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      'custom/no-empty-select-value': 'error',
      'custom/no-empty-dynamic-select-value': 'warn',
      'custom/no-mock-data': 'error',
    },
  },
  {
    files: ['**/components/ui/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
)
